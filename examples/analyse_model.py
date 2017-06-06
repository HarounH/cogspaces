import json
import os
from os.path import join

import matplotlib.pyplot as plt
import numpy as np
from keras.models import load_model
from keras.utils import CustomObjectScope
from modl.utils.system import get_cache_dirs
from nilearn._utils import check_niimg
from nilearn.datasets import fetch_atlas_msdl
from nilearn.image import new_img_like, index_img
from nilearn.input_data import NiftiLabelsMasker, MultiNiftiMasker
from nilearn.plotting import plot_stat_map, find_xyz_cut_coords
from sklearn.externals.joblib import Memory, load, delayed, Parallel
from sklearn.utils.extmath import randomized_svd

from cogspaces.datasets import fetch_craddock_parcellation, fetch_atlas_modl, \
    fetch_mask
from cogspaces.model import HierarchicalLabelMasking, PartialSoftmax, \
    make_projection_matrix, L1Init
from cogspaces.utils import get_output_dir

positive = False
n_exp = 133


def plot_map(single_map, title, i):
    fig = plt.figure()
    vmax = np.max(np.abs(single_map.get_data()))
    cut_coords = find_xyz_cut_coords(single_map,
                                     activation_threshold=0.33 * vmax)
    plot_stat_map(single_map, title=str(title), figure=fig,
                  cut_coords=cut_coords, threshold=0.)
    plt.savefig(join(analysis_dir, '%s.png' % title))
    plt.close(fig)


memory = Memory(cachedir=get_cache_dirs()[0], verbose=2)

artifact_dir = join(get_output_dir(), 'predict', str(n_exp))
analysis_dir = join(artifact_dir, 'analysis')
if not os.path.exists(analysis_dir):
    os.makedirs(analysis_dir)

config = json.load(open(join(artifact_dir, 'config.json'), 'r'))

if True: # config['latent_dim'] is not None:
    with CustomObjectScope({'l1_init': L1Init}):
        model = load_model(join(artifact_dir, 'artifacts', 'model.keras'),
                           custom_objects={'HierarchicalLabelMasking':
                                           HierarchicalLabelMasking,
                                           'PartialSoftmax': PartialSoftmax})

    supervised = model.get_layer('supervised_depth_1').get_weights()[0]
    print('sparsity', np.mean(supervised == 0))
    if positive:
        supervised[:, :30] -= supervised[:, :30].min()
        supervised[:, 30:] -= supervised[:, 30:].min()
    if config['latent_dim'] is not None:
        latent = model.get_layer('latent').get_weights()[0]
        maps = latent.dot(supervised).T
        if config['residual']:
            direct = model.get_layer('supervised_direct_depth_1').get_weights()[0].T
            direct -= direct.min()
            maps += direct
    else:
        maps = supervised.T
else:
    model = load(join(artifact_dir, 'artifacts', 'model.pkl'))
    maps = model.coef_

if positive:
    maps[:30] -= maps[:30].min()
    maps[30:] -= maps[30:].min()

source = config['source']

if source == 'craddock':
    components = fetch_craddock_parcellation().parcellate400
    data = np.ones_like(check_niimg(components).get_data())
    mask = new_img_like(components, data)
    label_masker = NiftiLabelsMasker(labels_img=components,
                                     smoothing_fwhm=0,
                                     mask_img=mask).fit()
    maps_img = label_masker.inverse_transform(maps)
else:
    mask = fetch_mask()
    masker = MultiNiftiMasker(mask_img=mask).fit()

    if source == 'msdl':
        components = fetch_atlas_msdl()['maps']
        components = masker.transform(components)
    elif source in ['hcp_rs', 'hcp_rs_concat', 'hcp_rs_positive']:
        data = fetch_atlas_modl()
        if source == 'hcp_rs':
            components_imgs = [data.nips2017_components64]
        elif source == 'hcp_rs_concat':
            components_imgs = [data.nips2017_components16,
                               data.nips2017_components64,
                               data.nips2017_components256]
        else:
            components_imgs = [data.positive_components16,
                               data.positive_components64,
                               data.positive_components512]
        components = masker.transform(components_imgs)
        proj, inv_proj, rec = memory.cache(
            make_projection_matrix)(components, scale_bases=True)

        U, S, VT = randomized_svd(maps, n_components=maps.shape[0])
        print(S)
        comp = VT.dot(proj.T)
        comp_img = masker.inverse_transform(comp)
        comp_img.to_filename(join(analysis_dir, 'comp.nii.gz'))

        maps = maps.dot(proj.T)
        if positive:
            maps[:30] -= maps[:30].min()
            maps[30:] -= maps[30:].min()
        maps_img = masker.inverse_transform(maps)

lbin = load(join(artifact_dir, 'artifacts', 'lbin.pkl'))
classes = lbin.classes_

maps_img.to_filename(join(analysis_dir, 'maps.nii.gz'))
Parallel(n_jobs=3, verbose=10)(delayed(plot_map)(index_img(maps_img, i),
                                                 classes[i], i) for
                   i in range(maps_img.shape[3]))

Parallel(n_jobs=3, verbose=10)(delayed(plot_map)(index_img(comp_img, i),
                                                 'map_%i' % i, i) for
                   i in range(maps_img.shape[3]))