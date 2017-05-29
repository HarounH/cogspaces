import os
from os.path import join

import pandas as pd
from modl.input_data.fmri.unmask import MultiRawMasker
from modl.utils.system import get_cache_dirs
from nilearn.datasets import fetch_atlas_msdl
from sklearn.externals.joblib import Memory, load, dump
from nilearn.input_data import MultiNiftiMasker, NiftiLabelsMasker
from sklearn.utils import gen_batches

from cogspaces import get_output_dir
from cogspaces.datasets import fetch_la5c, fetch_human_voice, fetch_brainomics, \
    fetch_camcan, fetch_hcp, fetch_archi, get_data_dirs

import numpy as np

from cogspaces.model import make_projection_matrix


def unmask(dataset, output_dir=None,
           n_jobs=1, batch_size=1000):
    if dataset == 'hcp':
        fetch_data = fetch_hcp
    elif dataset == 'archi':
        fetch_data = fetch_archi
    elif dataset == 'brainomics':
        fetch_data = fetch_brainomics
    elif dataset == 'la5c':
        fetch_data = fetch_la5c
    elif dataset == 'human_voice':
        fetch_data = fetch_human_voice
    elif dataset == 'camcan':
        fetch_data = fetch_camcan
    else:
        raise ValueError

    imgs = fetch_data()
    if dataset == 'hcp':
        imgs = imgs.contrasts
    mask = fetch_hcp(n_subjects=1).mask

    artifact_dir = join(get_output_dir(output_dir), dataset)

    create_raw_contrast_data(imgs, mask, artifact_dir, n_jobs=n_jobs,
                             batch_size=batch_size)


def create_raw_contrast_data(imgs, mask, raw_dir,
                             memory=Memory(cachedir=None),
                             n_jobs=1, batch_size=100):
    if not os.path.exists(raw_dir):
        os.makedirs(raw_dir)

    # Selection of contrasts
    masker = MultiNiftiMasker(smoothing_fwhm=0,
                              mask_img=mask,
                              memory=memory,
                              memory_level=1,
                              n_jobs=n_jobs).fit()
    mask_img_file = os.path.join(raw_dir, 'mask_img.nii.gz')
    masker.mask_img_.to_filename(mask_img_file)

    batches = gen_batches(len(imgs), batch_size)

    data = np.empty((len(imgs), masker.mask_img_.get_data().sum()),
                    dtype=np.float32)
    for i, batch in enumerate(batches):
        print('Batch %i' % i)
        data[batch] = masker.transform(imgs['z_map'].values[batch])
    imgs = pd.DataFrame(data=data, index=imgs.index, dtype=np.float32)
    dump(imgs, join(raw_dir, 'imgs.pkl'))


def get_raw_contrast_data(raw_dir):
    mask_img = os.path.join(raw_dir, 'mask_img.nii.gz')
    masker = MultiRawMasker(smoothing_fwhm=0, mask_img=mask_img)
    masker.fit()
    imgs = load(join(raw_dir, 'imgs.pkl'))
    return masker, imgs


def build_design(datasets, datasets_dir, n_subjects):
    X = []
    for dataset in datasets:
        masker, this_X = get_raw_contrast_data(datasets_dir[dataset])
        subjects = this_X.index.get_level_values(
            'subject').unique().values.tolist()

        subjects = subjects[:n_subjects]
        X.append(this_X.loc[subjects])
    X = pd.concat(X, keys=datasets, names=['dataset'])

    return X, masker


def reduce(dataset, output_dir=None, source='hcp_rs_concat'):
    memory = Memory(cachedir=get_cache_dirs()[0], verbose=2)
    print('Fetch data')
    this_dataset_dir = join(get_output_dir(output_dir), 'unmask', dataset)
    masker, X = get_raw_contrast_data(this_dataset_dir)
    print('Retrieve components')
    if source == 'craddock':
        components = join(get_data_dirs()[0],
                          'ADHD200_parcellations',
                          'ADHD200_parcellate_400.nii.gz')
        niimgs = masker.inverse_transform(X.values)
        label_masker = NiftiLabelsMasker(labels_img=components,
                                         smoothing_fwhm=0,
                                         mask_img=masker.mask_img_).fit()
        Xt = label_masker.transform(niimgs)
    else:
        if source == 'msdl':
            components = fetch_atlas_msdl()['maps']
            proj = masker.transform(components).T
        elif source in ['hcp_rs', 'hcp_rs_concat']:
            if source == 'hcp_rs':
                n_components_list = [64]
            else:
                n_components_list = [16, 64, 256]
            components_dir = join(get_data_dirs()[0], 'components',
                                  'hcp')
            components_imgs = [join(components_dir,
                                    str(n_components),
                                    str("1e-4"),
                                    'components.nii.gz')
                               for n_components in n_components_list]
            components = masker.transform(components_imgs)
            print('Transform and fit data')
            proj, _ = memory.cache(make_projection_matrix)(components,
                                                           scale_bases=True, )
        Xt = X.dot(proj)
    Xt = pd.DataFrame(data=Xt, index=X.index)
    this_output_dir = join(get_output_dir(output_dir), 'reduce', dataset)
    if not os.path.exists(this_output_dir):
        os.makedirs(this_output_dir)
    dump(Xt, join(this_output_dir, 'Xt.pkl'))
    dump(masker, join(this_output_dir, 'masker.pkl'))