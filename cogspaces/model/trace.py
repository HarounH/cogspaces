from math import sqrt

import numpy as np
from numba import jit
from numpy.linalg import svd
from sklearn.base import BaseEstimator
from sklearn.utils import check_array


def lipschitz_constant(Xs, dataset_weights, fit_intercept=False,
                       split_loss=False):
    max_squared_sums = np.array([(X ** 2).sum(axis=1).max() for X in Xs])
    if fit_intercept:
        max_squared_sums += 1
    max_squared_sums *= dataset_weights
    if split_loss:
        max_squared_sums = np.mean(max_squared_sums)
    else:
        max_squared_sums = np.max(max_squared_sums)
    L = 0.5 * max_squared_sums
    return L


@jit(nopython=True, cache=False)
def trace_norm(coef):
    _, s, _ = svd(coef, full_matrices=False)
    return np.sum(s)


@jit(nopython=True, cache=True)
def proximal_operator(coef, threshold):
    U, s, V = svd(coef, full_matrices=False)
    s = np.maximum(s - threshold, 0)
    rank = np.sum(s != 0)
    U *= s
    return np.dot(U, V), rank


@jit(nopython=True, cache=True)
def _prox_grad(Xs, ys, preds, coef, intercept,
               dataset_weights,
               prox_coef, prox_intercept, coef_grad, intercept_grad,
               slices, L, Lmax, alpha, beta, max_backtracking_iter,
               backtracking_divider,
               coef_diff, intercept_diff):
    n_datasets = len(slices)
    _predict(Xs, preds, coef, intercept, slices)
    loss = .5 * beta * np.sum(coef ** 2)
    coef_grad[:] = 0
    intercept_grad[:] = 0
    for X, y, pred, this_slice, dataset_weight in zip(Xs, ys, preds, slices, dataset_weights):
        coef_grad[:, this_slice[0]:this_slice[1]] += \
            np.dot(X.T, np.exp(pred) - y) / X.shape[0] / n_datasets * dataset_weight
        for jj, j in enumerate(range(this_slice[0], this_slice[1])):
            intercept_grad[j] += (np.exp(pred[:, jj]) - y[:, jj]).mean() / n_datasets * dataset_weight
        loss += cross_entropy(y, pred) / n_datasets * dataset_weight
    if beta > 0:
        coef_grad += beta * coef
    # Gradient step

    for j in range(max_backtracking_iter):
        prox_coef[:] = coef - coef_grad / L
        prox_intercept[:] = intercept - intercept_grad / L
        if alpha > 0:
            prox_coef[:], rank = proximal_operator(prox_coef, alpha / L)
        else:
            rank = prox_coef.shape[1]
        if j < max_backtracking_iter - 1:
            new_loss = _loss(Xs, ys, preds, dataset_weights,
                             prox_coef, prox_intercept,
                             slices, beta)
            quad_approx = _quad_approx(coef, intercept,
                                       prox_coef, prox_intercept,
                                       coef_grad, intercept_grad,
                                       coef_diff, intercept_diff,
                                       loss, L)
            if new_loss <= quad_approx:
                loss = new_loss
                break
            else:
                print('Backtracking')
                L *= backtracking_divider
                if L > Lmax:
                    L = Lmax
                    max_backtracking_iter = 1

    return loss, rank, L, max_backtracking_iter


@jit(nopython=True, cache=True)
def _predict(Xs, preds, coef, intercept, slices):
    for X, pred, this_slice in zip(Xs, preds, slices):
        pred[:] = np.dot(X, coef[:, this_slice[0]:this_slice[1]])
        pred += intercept[this_slice[0]:this_slice[1]]
        for i in range(pred.shape[0]):
            pred[i] -= pred[i].max()
            logsumexp = np.log(np.sum(np.exp(pred[i])))
            pred[i] -= logsumexp


@jit(nopython=True, cache=True)
def _loss(Xs, ys, preds, dataset_weights, coef, intercept, slices, beta):
    n_datasets = len(slices)
    _predict(Xs, preds, coef, intercept, slices)
    loss = .5 * beta * np.sum(coef ** 2)
    for y, pred, dataset_weight in zip(ys, preds, dataset_weights):
        loss += cross_entropy(y, pred) / n_datasets * dataset_weight
    return loss


@jit(nopython=True, cache=True)
def _quad_approx(coef, intercept,
                 prox_coef, prox_intercept, coef_grad,
                 intercept_grad,
                 coef_diff, intercept_diff,
                 loss, L):
    approx = loss
    coef_diff[:] = prox_coef - coef
    intercept_diff[:] = prox_intercept - intercept
    approx += np.sum(coef_diff * coef_grad)
    approx += np.sum(intercept_diff * intercept_grad)
    approx += .5 * L * (np.sum(coef_diff ** 2) + np.sum(intercept_diff ** 2))
    return approx


@jit("float32(i8[:, :], f4[:, :])", nopython=True)
def cross_entropy(y_true, y_pred):
    n_samples, n_targets = y_true.shape
    loss = 0
    for i in range(n_samples):
        for j in range(n_targets):
            if y_true[i, j]:
                loss -= y_pred[i, j]
    return loss / n_samples


@jit(nopython=True, cache=True)
def _ista_loop(L, Lmax, Xs, coef, coef_diff, coef_grad, intercept,
               dataset_weights,
               intercept_diff, intercept_grad, old_prox_coef, preds,
               prox_coef, prox_intercept, ys,
               max_iter, max_backtracking_iter, slices, alpha, beta,
               backtracking_divider,
               verbose, momentum):
    old_prox_coef[:] = 0
    t = 1
    _predict(Xs, preds, coef, intercept, slices)
    loss = _loss(Xs, ys, preds, dataset_weights, coef, intercept, slices, beta)
    rank = np.linalg.matrix_rank(coef)
    for iter in range(max_iter):
        if verbose and iter % (max_iter // verbose) == 0:
            if alpha > 0:
                loss += alpha * trace_norm(coef)
            print('Iteration', iter, 'rank', rank, 'loss', loss,
                  'step size', 1 / L)

        loss, rank, L, max_backtracking_iter = _prox_grad(Xs, ys, preds, coef,
                                                          intercept,
                                                          dataset_weights,
                                                          prox_coef,
                                                          prox_intercept,
                                                          coef_grad,
                                                          intercept_grad,
                                                          slices, L, Lmax,
                                                          alpha,
                                                          beta,
                                                          max_backtracking_iter,
                                                          backtracking_divider,
                                                          coef_diff,
                                                          intercept_diff)

        if momentum:
            old_t = t
            t = .5 * (1 + sqrt(1 + 4 * old_t ** 2))
            # Write inplace so that coefs stays valid
            coef[:] = prox_coef * (1 + (old_t - 1) / t)
            coef -= (old_t - 1) / t * old_prox_coef
            old_prox_coef[:] = prox_coef
        else:
            coef[:] = prox_coef
        intercept[:] = prox_intercept


class TraceNormEstimator(BaseEstimator):
    def __init__(self, alpha=1., beta=0., max_iter=1000,
                 momentum=True,
                 fit_intercept=True,
                 verbose=False,
                 max_backtracking_iter=5,
                 step_size_multiplier=1,
                 backtracking_divider=2.,
                 rescale_weights=False,
                 split_loss=True):
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.max_iter = max_iter
        self.fit_intercept = fit_intercept
        self.rescale_weights = rescale_weights
        self.momentum = momentum
        self.verbose = verbose

        self.backtracking_divider = float(backtracking_divider)
        self.max_backtracking_iter = max_backtracking_iter
        self.init_multiplier = float(step_size_multiplier)
        self.split_loss = split_loss

    def fit(self, Xs, ys, dataset_weights=None):
        n_datasets = len(Xs)
        n_features = Xs[0].shape[1]

        Xs, ys = check_Xs_ys(Xs, ys)

        sizes = np.array([this_y.shape[1] for this_y in ys], dtype=np.int64)
        limits = [0] + np.cumsum(sizes).tolist()
        total_size = limits[-1]

        if dataset_weights is None:
            dataset_weights = np.ones(n_datasets, dtype=np.float32)
        else:
            dataset_weights = np.array(dataset_weights, dtype=np.float32)
            dataset_weights /= np.mean(dataset_weights)
            print(dataset_weights)
        # if self.rescale_weights:
        #     dataset_weights = np.array(dataset_weights) * np.sqrt([X.shape[0]
        #                                                            for X in Xs])
        #     dataset_weights /= np.sum(dataset_weights) / n_datasets

        self.slices_ = []
        for iter in range(n_datasets):
            self.slices_.append(np.array([limits[iter], limits[iter + 1]]))
        self.slices_ = tuple(self.slices_)

        if self.split_loss:
            ys_ = tuple(np.zeros((y.shape[0], total_size), dtype=np.int64) for y in ys)
            for y_, y, this_slice in zip(ys_, ys, self.slices_):
                y_[:, this_slice[0]:this_slice[1]] = y
            training_slices = tuple([np.array([0, total_size])] * n_datasets)
            ys = ys_
        else:
            training_slices = self.slices_

        Lmax = lipschitz_constant(Xs, dataset_weights, self.fit_intercept,
                                  self.split_loss)
        L = Lmax / self.init_multiplier
        coef = np.ones((n_features, total_size), dtype=np.float32)
        intercept = np.zeros(total_size, dtype=np.float32)

        prox_coef = np.empty_like(coef, dtype=np.float32)
        coef_grad = np.empty_like(coef, dtype=np.float32)
        prox_intercept = np.empty_like(intercept, dtype=np.float32)
        intercept_grad = np.empty_like(intercept, dtype=np.float32)
        coef_diff = np.empty_like(coef, dtype=np.float32)
        intercept_diff = np.empty_like(intercept, dtype=np.float32)
        old_prox_coef = np.empty_like(coef)

        preds = tuple(np.empty_like(y, dtype=np.float32) for y in ys)

        _ista_loop(L, Lmax, Xs, coef, coef_diff, coef_grad, intercept,
                   dataset_weights,
                   intercept_diff, intercept_grad, old_prox_coef,
                   preds, prox_coef, prox_intercept, ys,
                   self.max_iter, self.max_backtracking_iter, training_slices,
                   self.alpha, self.beta,
                   self.backtracking_divider,
                   self.verbose, self.momentum
                   )
        self.coef_ = coef
        self.intercept_ = intercept

    def score(self, Xs, ys):
        Xs, ys = check_Xs_ys(Xs, ys)
        preds = self.predict(Xs)
        scores = []
        for pred, y in zip(preds, ys):
            scores.append(cross_entropy(y, pred))
        return scores

    def predict(self, Xs):
        Xs = tuple(check_array(X, dtype=np.float32) for X in Xs)
        preds = tuple(np.empty((X.shape[0], this_slice[1] - this_slice[0]),
                               dtype=np.float32)
                      for X, this_slice in zip(Xs, self.slices_))
        _predict(Xs, preds, self.coef_, self.intercept_, self.slices_)
        return tuple(np.exp(pred) for pred in preds)


def check_Xs_ys(Xs, ys):
    Xs = tuple(check_array(X, dtype=np.float32) for X in Xs)
    ys = tuple(check_array(y, dtype=np.int64) for y in ys)
    return Xs, ys