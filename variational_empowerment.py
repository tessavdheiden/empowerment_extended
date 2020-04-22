import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np


class Source(nn.Module):
    categorical_dim = 5
    def __init__(self, input_dim):
        super(Source, self).__init__()
        self.input_dim = input_dim
        self.fc = nn.Linear(self.input_dim, 100)
        self.a_head = nn.Linear(100, self.categorical_dim)

    def forward(self, x):
        x = F.relu(self.fc(x))
        action_score = self.a_head(x)
        return F.gumbel_softmax(action_score, tau=1, hard=True, dim=-1)

class Planner(nn.Module):
    categorical_dim = 5
    def __init__(self, input_dim):
        super(Planner, self).__init__()
        self.input_dim = input_dim
        self.fc = nn.Linear(self.input_dim, 100)
        self.fc_ = nn.Linear(self.input_dim, 100)
        self.hidden = nn.Linear(200, 200)
        self.a_head = nn.Linear(200, self.categorical_dim)

    def forward(self, x, x_):
        x = F.relu(self.fc(x))
        x_ = F.relu(self.fc_(x_))
        cat = torch.cat([x, x_], dim=-1)
        h = F.relu(self.hidden(cat))
        action_score = self.a_head(h)
        return F.softmax(action_score, dim=-1)


class VariationalEmpowerment(object):
    max_grad_norm = .5
    def __init__(self, input_dim):
        self.input_dim = input_dim
        self.source = Source(input_dim)
        self.planner = Planner(input_dim)
        self.optimizer_planner = optim.Adam(self.planner.parameters(), lr=3e-4)
        self.optimizer_source = optim.Adam(self.source.parameters(), lr=3e-4)
        self.action_list = numpy_to_torch(np.arange(5)).view(1, -1)

    def compute(self, state, T, n_samples=1000):
        T = numpy_to_torch(T)
        s = torch.tensor(state).long().view(-1, 1)
        E = 0
        s_hot = one_hot_vector(s, self.input_dim)
        for i in range(n_samples):
            with torch.no_grad():
                z = self.source.forward(s_hot)
                a = torch.mm(z, self.action_list.T)
                s_ = torch.mm(T[:, :, int(s.item())], z.T).T
                prob_ = self.planner.forward(s_hot, s_)
                E += int(prob_.max(1)[1] == a.long()) #torch.mm(prob_, z.T)#
        return E / n_samples

    def train(self, T, n_samples=10000):
        n_states, n_actions, _ = T.shape
        T = numpy_to_torch(T)
        for i in range(n_samples):
            s = (torch.rand(1)*self.input_dim).long().view(-1, 1)
            s_hot = one_hot_vector(s, self.input_dim)
            z = self.source.forward(s_hot)

            s_ = get_s_next_from_one_hot(T, s_hot, z)

            prob_ = self.planner.forward(s_hot, s_.detach())

            self.optimizer_planner.zero_grad()
            loss = -torch.mm(prob_, z.T) -torch.mm(prob_, (z - 1).T)
            loss.backward()
            nn.utils.clip_grad_norm_(self.planner.parameters(),
                                     self.max_grad_norm)
            self.optimizer_planner.step()

    def train_batch(self, T, n_samples=int(5e4), n_b=2**5):
        n_states, n_actions, _ = T.shape
        T = numpy_to_torch(T)
        for i in range(n_samples):
            S = (torch.rand(n_b) * self.input_dim).long().view(-1, 1)
            S_hot = one_hot_batch_matrix(S, self.input_dim)
            Z = self.source.forward(S_hot.float())

            S_ = get_s_next_from_one_hot_batch_matrix(T, S_hot, Z)

            prob_ = self.planner.forward(S_hot, S_.detach())

            self.optimizer_planner.zero_grad()
            error = -torch.mul(prob_, Z).sum(1) -torch.mul(prob_, (Z - 1)).sum(1)
            loss = error.mean()
            loss.backward()
            nn.utils.clip_grad_norm_(self.planner.parameters(),
                                     self.max_grad_norm)
            self.optimizer_planner.step()


def numpy_to_torch(x):
    return torch.from_numpy(x).float()

def one_hot_vector(x, input_dim):
    return torch.zeros(1, input_dim).scatter_(1, x.view(-1, 1), 1)

def one_hot_batch_matrix(x, input_dim):
    return torch.zeros(x.shape[0], input_dim).scatter_(1, x.view(-1, 1), 1)

def get_s_next_from_one_hot(T, s_hot, z):
    assert s_hot.shape[1] > 1
    t = (T * s_hot.float()).sum(2)
    return torch.mm(t, z.float().T).T

def get_s_next(T, s, z):
    assert s.shape[1] == 1
    idx = s.unsqueeze(0).repeat(T.shape[0], T.shape[1], 1)
    t = T[:, :, :].gather(2, idx)
    return torch.mm(t.squeeze(2), z.T).T

def get_s_next_from_one_hot_batch_matrix(T, s_hot, z):
    assert s_hot.shape[0] > 1 and z.shape[0] > 1
    n_s, n_a, _ = T.shape
    n_b, _ = s_hot.shape
    t = T.view(-1, n_s * n_a, n_s)
    t = t.repeat(n_b, 1, 1)
    s_hot = s_hot.view(n_b, n_s, 1)

    batch = torch.bmm(t.float(), s_hot.float()) # out = [n_b, n_s * n_a, 1]
    batch = batch.squeeze(2).view(n_b, n_s, n_a)
    z = z.view(n_b, n_a, 1)

    out = torch.bmm(batch, z.float()) # out = [n_b, n_s, 1]
    return out.squeeze(2)



