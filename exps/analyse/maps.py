import numpy as np
import os
import re
import torch
from joblib import load, delayed, Parallel
from nilearn.input_data import NiftiMasker
from os.path import join

from cogspaces.datasets.dictionaries import fetch_atlas_modl
from cogspaces.datasets.utils import fetch_mask, get_output_dir, get_data_dir
from cogspaces.plotting import plot_all
from exps.train import load_data


def inspect_components(output_dir, n_jobs=3):
    estimator = load(join(output_dir, 'estimator.pkl'))
    components = estimator.module_.embedder.linear.weight.detach().numpy()
    dictionary, masker = get_proj_and_masker()
    components = components.dot(dictionary)
    components = masker.inverse_transform(components)
    filename = join(output_dir, 'components.nii.gz')
    components.to_filename(filename)

    # plot_all(filename, output_dir=join(output_dir, 'components'),
    #          name='components', n_jobs=n_jobs, verbose=0)


def inspect_components_dl(output_dir, n_jobs=3):
    estimator = load(join(output_dir, 'estimator.pkl'))
    components = estimator.components_
    components_dl = estimator.components_dl_
    dictionary, masker = get_proj_and_masker()

    comp_to_plot = {'components': components,
                    'component_dl': components_dl}

    print(components)
    print(components_dl)

    for name, this_comp in comp_to_plot.items():
        this_comp = this_comp.dot(dictionary)
        this_comp = masker.inverse_transform(this_comp)
        filename = join(output_dir, '%s.nii.gz' % name)
        this_comp.to_filename(filename)
        plot_all(filename, output_dir=join(output_dir, name),
                 name=name, n_jobs=n_jobs, verbose=0)


def inspect_classification(output_dir, n_jobs=3):
    estimator = load(join(output_dir, 'estimator.pkl'))
    target_encoder = load(join(output_dir, 'target_encoder.pkl'))
    module = estimator.classifier_.module_

    data, target = load_data(join(get_data_dir(), 'reduced_512'), 'all')
    target = target_encoder.transform(target)

    data = {study: torch.from_numpy(this_data).float() for study, this_data in
            data.items()}
    target = {study: torch.from_numpy(this_target['contrast'].values) for study, this_target
              in target.items()}

    module.eval()

    with torch.no_grad():
        preds = []
        names = []
        for study, this_data in data.items():
            this_target = target[study]
            contrasts = target_encoder.le_[study]['contrast'].classes_
            for contrast in range(len(contrasts)):
                data_contrast = this_data[this_target
                                          == contrast].mean(dim=0, keepdim=True)
                pred = module.embedder(data_contrast)
                preds.append(pred)
            names.extend(['%s_%s' % (study, name) for name in contrasts])
        preds = torch.cat(preds, dim=0)
        preds -= torch.mean(preds, dim=1, keepdim=True)
        preds /= torch.sqrt(torch.sum(preds ** 2, dim=1, keepdim=True))
        preds = preds.numpy()
    names = np.array(names)
    for i in range(preds.shape[1]):
        sort = np.argsort(preds[:, i])[::-1]
        print(preds[:, i][sort][:10])
        print(names[sort][:10])

    # classification = []
    # preds = []
    # names = []
    # for study, classifier in module.classifiers.items():
    #     classifier_coef = classifier.linear.weight.detach()
    #     multiplier = (classifier.batch_norm.weight.detach()\
    #                   / torch.sqrt(classifier.batch_norm.running_var))
    #     classifier_coef *= multiplier
    #
    #     classifier_coef = classifier_coef.numpy()
    #
    #     with torch.no_grad():
    #         latent_size = classifier_coef.shape[1]
    #         input = torch.diag(torch.from_numpy(mean)).float()
    #         input += module.embedder.linear.bias[None, :]
    #         classifier.eval()
    #         pred = F.softmax(classifier(input), dim=1)
    #         pred = pred.detach().numpy()
    #         print('---------------')
    #         print(study)
    #         print('---------------')
    #         print(np.array2string(pred, precision=3))
    #         classification.append(classifier_coef)
    #         preds.append(pred)
    #         these_names = np.array(['%s_%s' % (study, name) for name in
    #                        target_encoder.le_[study]['contrast'].classes_])
    #         names.append(these_names)

    # classification = np.concatenate(classification, axis=0)
    # names = np.concatenate(names)
    #
    # classifications = {'classification': classification,}
    #
    # dump(classifications, join(output_dir, 'classifications.pkl'))
    #
    # for i in range(classification_std.shape[1]):
    #     sort = np.argsort(classification_std[:, i])[::-1]
    #     print(classification_std[:, i][sort][:5])
    #     print(names[sort][:5])

    # for name, classif in classifications.items():
    #     classif = classif.dot(dictionary)
    #     classif = masker.inverse_transform(classif)
    #     filename = join(output_dir, '%s.nii.gz' % name)
    #     classif.to_filename(filename)
        # plot_all(filename, name=name,
        #          names=names,
        #          output_dir=join(output_dir, 'components'),
        #          n_jobs=n_jobs)


def get_proj_and_masker():
    modl_atlas = fetch_atlas_modl()
    dictionary = modl_atlas['components512']
    mask = fetch_mask()['hcp']
    masker = NiftiMasker(mask_img=mask).fit()
    dictionary = masker.transform(dictionary)
    return dictionary, masker


def inspect_all(output_dir, n_jobs=1):
    regex = re.compile(r'[0-9]+$')
    Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(inspect_components)(join(output_dir, this_dir), n_jobs=1)
        for this_dir in filter(regex.match, os.listdir(output_dir)))


if __name__ == '__main__':
    # inspect_all(join(get_output_dir(), 'factored_sparsify'), n_jobs=10)
    # inspect_all(join(get_output_dir(), 'factored_refit_cautious'), n_jobs=10)
    # inspect_all(join(get_output_dir(), 'factored_sparsify_less'), n_jobs=10)
    # inspect_components_dl(join(get_output_dir(), 'single_full'), n_jobs=3)
    inspect_classification(join(get_output_dir(), 'single_full'), n_jobs=3)
    # inspect_components(join(get_output_dir(), 'multi_studies'))