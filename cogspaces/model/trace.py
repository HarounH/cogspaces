from math import sqrt

import numpy as np
from numba import jit
from numpy.linalg import svd
from sklearn.base import BaseEstimator
from sklearn.utils import check_array

def lipschitz_constant(X, dataset_weights, xslices, fit_intercept=False,
                       split_loss=False):
    Xs = [X[xslice[0]:xslice[1]] for xslice in xslices]
    max_squared_sums = np.array([(X ** 2).sum(axis=1).max() for X in Xs])
    if fit_intercept:
        max_squared_sums += 1
    max_squared_sums *= dataset_weights
    if split_loss:
        max_squared_sums = np.sum(max_squared_sums)
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
def _prox_grad(X, y, pred, coef, intercept,
               dataset_weights,
               prox_coef, prox_intercept, coef_grad, intercept_grad,
               xslices, yslices, L, Lmax, alpha, beta, max_backtracking_iter,
               backtracking_divider,
               coef_diff, intercept_diff):
    _predict(X, pred, coef, intercept, xslices, yslices)
    loss = .5 * beta * np.sum(coef ** 2)
    coef_grad[:] = 0
    intercept_grad[:] = 0
    n_datasets = len(xslices)
    for i in range(n_datasets):
        xslice, yslice, dataset_weight = xslices[i], yslices[i], \
                                         dataset_weights[i]
        this_X = X[xslice[0]:xslice[1]]
        this_y = y[xslice[0]:xslice[1], yslice[0]:yslice[1]]
        this_pred = pred[xslice[0]:xslice[1], yslice[0]:yslice[1]]
        coef_grad[:, yslice[0]:yslice[1]] += \
            np.dot(this_X.T, np.exp(this_pred) - this_y) / this_X.shape[
                0] * dataset_weight
        for jj, j in enumerate(range(yslice[0], yslice[1])):
            intercept_grad[j] += (np.exp(this_pred[:, jj]) - this_y[:,
                                                             jj]).mean() * dataset_weight
        loss += cross_entropy(this_y, this_pred) * dataset_weight
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
            new_loss = _loss(X, y, pred, dataset_weights,
                             prox_coef, prox_intercept,
                             xslices, yslices, beta)
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
def _predict(X, pred, coef, intercept, xslices, yslices):
    n_datasets = len(xslices)
    for i in range(n_datasets):
        xslice, yslice = xslices[i], yslices[i]
        pred[xslice[0]:xslice[1], yslice[0]:yslice[1]] = np.dot(
            X[xslice[0]:xslice[1]], coef[:, yslice[0]:yslice[1]])
        pred[:, yslice[0]:yslice[1]] += intercept[yslice[0]:yslice[1]]
        for i in range(pred.shape[0]):
            pred[i] -= pred[i].max()
            logsumexp = np.log(np.sum(np.exp(pred[i])))
            pred[i] -= logsumexp


@jit(nopython=True, cache=True)
def _loss(X, y, pred, dataset_weights, coef, intercept,
          xslices, yslices, beta):
    _predict(X, pred, coef, intercept, xslices, yslices)
    loss = .5 * beta * np.sum(coef ** 2)
    n_datasets = len(xslices)
    for i in range(n_datasets):
        xslice, yslice, dataset_weight = xslices[i], yslices[i], \
                                         dataset_weights[i]
        this_y = y[xslice[0]:xslice[1], yslice[0]:yslice[1]]
        this_pred = pred[xslice[0]:xslice[1], yslice[0]:yslice[1]]
        loss += cross_entropy(this_y, this_pred) * dataset_weight
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


@jit(nopython=True)
def cross_entropy(y_true, y_pred):
    n_samples, n_targets = y_true.shape
    loss = 0
    for i in range(n_samples):
        for j in range(n_targets):
            if y_true[i, j]:
                loss -= y_pred[i, j]
    return loss / n_samples


@jit(nopython=True, cache=True)
def _ista_loop(L, Lmax, X, coef, coef_diff, coef_grad, intercept,
               dataset_weights,
               intercept_diff, intercept_grad, old_prox_coef, preds,
               prox_coef, prox_intercept, y,
               max_iter, max_backtracking_iter, xslices, yslices,
               alpha, beta,
               backtracking_divider,
               verbose, momentum):
    old_prox_coef[:] = 0
    t = 1
    _predict(X, preds, coef, intercept, xslices, yslices)
    loss = _loss(X, y, preds, dataset_weights, coef, intercept, xslices,
                 yslices, beta)
    rank = np.linalg.matrix_rank(coef)
    for iter in range(max_iter):
        if verbose and iter % (max_iter // verbose) == 0:
            if alpha > 0:
                loss += alpha * trace_norm(coef)
            print('Iteration', iter, 'rank', rank, 'loss', loss,
                  'step size', 1 / L)

        loss, rank, L, max_backtracking_iter = _prox_grad(X, y, preds, coef,
                                                          intercept,
                                                          dataset_weights,
                                                          prox_coef,
                                                          prox_intercept,
                                                          coef_grad,
                                                          intercept_grad,
                                                          xslices, yslices, L,
                                                          Lmax,
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
                 split_loss=True):
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.max_iter = max_iter
        self.fit_intercept = fit_intercept
        self.momentum = momentum
        self.verbose = verbose

        self.backtracking_divider = float(backtracking_divider)
        self.max_backtracking_iter = max_backtracking_iter
        self.init_multiplier = float(step_size_multiplier)
        self.split_loss = split_loss

    def fit(self, Xs, ys, dataset_weights=None):
        n_datasets = len(Xs)

        if dataset_weights is None:
            dataset_weights = np.ones(n_datasets, dtype=np.float32)
        else:
            dataset_weights = np.array(dataset_weights, dtype=np.float32)
            dataset_weights /= np.mean(dataset_weights)

        X, y, xslices, yslices = check_Xs_ys(Xs, ys)
        n_samples, n_features = X.shape
        n_targets = y.shape[1]

        self.yslices_ = yslices

        Lmax = lipschitz_constant(X, dataset_weights, xslices,
                                  self.fit_intercept, self.split_loss)
        L = Lmax / self.init_multiplier
        coef = np.ones((n_features, n_targets), dtype=np.float32)
        intercept = np.zeros(n_targets, dtype=np.float32)

        prox_coef = np.empty_like(coef, dtype=np.float32)
        coef_grad = np.empty_like(coef, dtype=np.float32)
        prox_intercept = np.empty_like(intercept, dtype=np.float32)
        intercept_grad = np.empty_like(intercept, dtype=np.float32)
        coef_diff = np.empty_like(coef, dtype=np.float32)
        intercept_diff = np.empty_like(intercept, dtype=np.float32)
        old_prox_coef = np.empty_like(coef)

        pred = np.empty_like(y, dtype=np.float32)

        _ista_loop(L, Lmax, X, coef, coef_diff, coef_grad, intercept,
                   dataset_weights,
                   intercept_diff, intercept_grad, old_prox_coef,
                   pred, prox_coef, prox_intercept, y,
                   self.max_iter, self.max_backtracking_iter, xslices,
                   yslices,
                   self.alpha, self.beta,
                   self.backtracking_divider,
                   self.verbose, self.momentum
                   )
        self.coef_ = coef
        self.intercept_ = intercept

    def predict(self, Xs):
        yslices = self.yslices_
        n_targets = yslices[-1, 1]
        X, xslices = check_Xs(Xs)
        n_samples = X.shape[0]
        pred = np.empty((n_samples, n_targets), dtype=np.float32)
        _predict(X, pred, self.coef_, self.intercept_, xslices, yslices)
        preds = []
        for xslice, yslice in zip(xslices, yslices):
            preds.append(np.exp(pred[xslice[0]:xslice[1],
                                yslice[0]:yslice[1]]))
        return tuple(preds)


def check_Xs(Xs):
    Xs = tuple(check_array(X, dtype=np.float32) for X in Xs)
    len_X = [X.shape[0] for X in Xs]
    cum_len_X = np.array([0] + np.cumsum(np.array(len_X)).tolist())[:,
                np.newaxis]
    xslices = np.hstack([cum_len_X[:-1], cum_len_X[1:]])
    X = np.concatenate(Xs)
    return X, xslices


def check_Xs_ys(Xs, ys):
    Xs = tuple(check_array(X, dtype=np.float32) for X in Xs)
    ys = tuple(check_array(y, dtype=np.int64) for y in ys)
    len_X = [X.shape[0] for X in Xs]
    len_y = [y.shape[1] for y in ys]
    cum_len_X = np.array([0] + np.cumsum(np.array(len_X)).tolist())[:,
                np.newaxis]
    cum_len_y = np.array([0] + np.cumsum(np.array(len_y)).tolist())[:,
                np.newaxis]
    xslices = np.hstack([cum_len_X[:-1], cum_len_X[1:]])
    yslices = np.hstack([cum_len_y[:-1], cum_len_y[1:]])
    X = np.concatenate(Xs)
    n_samples = xslices[-1, 1]
    n_targets = yslices[-1, 1]
    y_new = np.zeros((n_samples, n_targets), dtype=np.int64)
    for y, xslice, yslice in zip(ys, xslices, yslices):
        y_new[xslice[0]:xslice[1], yslice[0]:yslice[1]] = y
    return X, y_new, xslices, yslices
