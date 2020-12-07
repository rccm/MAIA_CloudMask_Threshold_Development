import h5py
import numpy as np
from rgb_enhancement import get_enhanced_RGB
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib
import matplotlib.colors as matCol
from matplotlib.colors import ListedColormap
import os
import configparser

#read in config file
config_home_path = '/data/keeling/a/vllgsbr2/c/MAIA_thresh_dev/MAIA_CloudMask_Threshold_Development'
config = configparser.ConfigParser()
config.read(config_home_path+'/test_config.txt')

PTA          = config['current PTA']['PTA']
PTA_path     = config['PTAs'][PTA]

#grab output files
MCM_output_home = '/data/keeling/a/vllgsbr2/c/old_MAIA_Threshold_dev/PTAs/LosAngeles/results/MCM_Output/Guangyu_output_dec_1_2020/'
time_stamps     = np.sort(os.listdir(MCM_output_home))

#grab input files
MCM_input_home = '/data/gdi/c/gzhao1/MCM-thresholds/PTAs/LosAngeles/MCM_Input/'
test_data_JPL_paths = os.listdir(MCM_input_home)
time_stamps         = [x[14:26] for x in test_data_JPL_paths]
test_data_JPL_paths = [MCM_input_home + x for x in test_data_JPL_paths]

for time_stamp, test_data_JPL_path in zip(time_stamps, test_data_JPL_paths):
    output_file_path = MCM_output_home + time_stamp + '/MCM_Output.h5'
    with h5py.File(output_file_path, 'r') as hf_MCM_output:
        DTT = hf_MCM_output['cloud_mask_output/DTT'][()]
        MCM = hf_MCM_output['cloud_mask_output/final_cloud_mask'][()]
        SID = hf_MCM_output['Ancillary/scene_type_identifier'][()]

        #get RGB
        R_red = hf_MCM_output['Reflectance/band_06'][()]
        R_grn = hf_MCM_output['Reflectance/band_05'][()]
        R_blu = hf_MCM_output['Reflectance/band_04'][()]

        #if no data anywhere just goto next file
        if np.all(R_red==-999):
            continue
        RGB = np.dstack((R_red, R_grn, R_blu))
        RGB = np.flip(RGB, 2)
        RGB[RGB==-999] = 0
        RGB = get_enhanced_RGB(RGB)

    #grab mod35 cm from input file
    with h5py.File(test_data_JPL_path, 'r') as hf_output:
        mod35cm = hf_output['MOD35_cloud_mask'][()]

    #plot
    #DTT_WI, DTT_NDVI, DTT_NDSI, DTT_VIS_Ref, DTT_NIR_Ref, DTT_SVI, DTT_Cirrus
    obs_namelist = ['WI', 'NDVI', 'NDSI', '0.65µm BRF', '0.86µm', 'SVI', 'Cirrus']
    f, ax = plt.subplots(nrows=2, ncols=6)

    for i, a in enumerate(ax.flat):

        #plot DTT first
        if i < 7:
            im = a.imshow(DTT[:,:,i], vmin=-101, vmax=101, cmap='bwr')
            a.set_title(obs_namelist[i])
            im.cmap.set_under('k')

        #plot BRF/MOD35/MCM/SID
        elif i==7:
            im = a.imshow(RGB, vmin=0)
            a.set_title('RGB')
        elif i==8:
            a.set_title('MOD35')
            cmap = ListedColormap(['white', 'green', 'blue','black'])
            norm = matCol.BoundaryNorm(np.arange(0,5,1), cmap.N)
            im = a.imshow(mod35cm, vmin=0, vmax=3, cmap=cmap, norm=norm)
            # cbar = plt.colorbar()
            cbar = f.colorbar(im)
            cbar.set_ticks([0.5,1.5,2.5,3.5])
            cbar.set_ticklabels(['cloudy', 'uncertain\nclear', \
                                 'probably\nclear', 'confident\nclear'])

        elif i==9:
            im = a.imshow(MCM, vmin=0, vmax=1, cmap='binary')
            a.set_title('MCM')
        elif i==10:
            im = a.imshow(SID, vmin=0, cmap='jet')
            a.set_title('SID')

        #turn off unused axes
        else:
            a.axis('off')
        #turn off ticks
        a.set_xticks([])
        a.set_yticks([])

        if i>7:
            im.cmap.set_under('r')
            im.cmap.set_over('r')

    plt.show()
