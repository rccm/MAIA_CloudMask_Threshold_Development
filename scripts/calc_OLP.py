import numpy as np

def get_sun_glint_mask(solarZenith, sensorZenith, solarAzimuth, sensorAzimuth,\
                       sun_glint_exclusion_angle, sfc_ID, num_land_sfc_types):
    """
    Calculate sun-glint flag.

    [Section 3.3.2.3]
    Sun-glint water pixels are set to 0;
    non-sun-glint water pixels and land pixels are set to 1.

    Arguments:
        solarZenith {2D narray} -- Solar zenith angle in degree
        sensorZenith {2D narray} -- MAIA zenith angle in degree
        solarAzimuth {2D narray} -- Solar azimuth angle in degree
        sensorAzimuth {2D narray} -- MAIA azimuth angle in degree
        sun_glint_exclusion_angle {float} -- maximum scattering angle (degree) for sun-glint
        land_water_mask {2D binary narray} -- specify the pixel is water (0) or land (1)

    Returns:
        2D binary narray -- sunglint mask over granule same shape as solarZenith
    """

    solarZenith               = np.deg2rad(solarZenith)
    sensorZenith              = np.deg2rad(sensorZenith)
    solarAzimuth              = np.deg2rad(solarAzimuth)
    sensorAzimuth             = np.deg2rad(sensorAzimuth)
    sun_glint_exclusion_angle = np.deg2rad(sun_glint_exclusion_angle)

    cos_theta_r = np.sin(sensorZenith) * np.sin(solarZenith) \
                * np.cos(sensorAzimuth - solarAzimuth - np.pi ) + np.cos(sensorZenith) \
                * np.cos(solarZenith)
    theta_r = np.arccos(cos_theta_r)

    sun_glint_idx = np.where((theta_r >= 0) & \
                             (theta_r <= sun_glint_exclusion_angle))
    no_sun_glint_idx = np.where(~((theta_r >= 0) & \
                                  (theta_r <= sun_glint_exclusion_angle)))
    theta_r[sun_glint_idx]    = 0
    theta_r[no_sun_glint_idx] = 1
    #turn off glint calculated over land
    water = num_land_sfc_types
    theta_r[sfc_ID != water] = 1

    sun_glint_mask = theta_r

    return sun_glint_mask

def get_observable_level_parameter(SZA, VZA, SAA, VAA, Target_Area,\
          snow_ice_mask, sfc_ID, DOY, sun_glint_mask,\
          num_land_sfc_types):

    """
    Objective:
        calculate bins of each pixel to query the threshold database
    [Section 3.3.2.2]
    Arguments:
        SZA {2D narray} -- solar zenith angle in degrees
        VZA {2D narray} -- viewing (MAIA) zenith angle in degrees
        SAA {2D narray} -- solar azimuth angle in degrees
        VAA {2D narray} -- viewing (MAIA) azimuth angle in degrees
        Target_Area {integer} -- number assigned to target area
        land_water_mask {2D narray} -- land (1) water(0)
        snow_ice_mask {2D narray} -- no snow/ice (1) snow/ice (0)
        sfc_ID {3D narray} -- surface ID anicillary dataset for target area
        DOY {integer} -- day of year in julian calendar
        sun_glint_mask {2D narray} -- no glint (1) sunglint (0)
    Returns:
        3D narray -- 3rd axis contains 9 integers that act as indicies to query
                     the threshold database for every observable level parameter.
                     The 1st and 2cnd axes are the size of the MAIA granule.
    """
    #This is used to determine if the test should be applied over a particular
    #surface type in the get_test_determination function
    shape = np.shape(SZA)
    #define relative azimuth angle, RAZ, and cos(SZA)
    RAZ = VAA - SAA
    RAZ[RAZ<0] = RAZ[RAZ<0]*-1
    RAZ[RAZ > 180.] = -1 * RAZ[RAZ > 180.] + 360. #symmtery about principle plane
    cos_SZA = np.cos(np.deg2rad(SZA))

    #bin each input, then dstack them. return this result
    #define bins for each input
    bin_cos_SZA = np.arange(0.1, 1.1 , 0.1)
    bin_VZA     = np.arange(5. , 75. , 5.) #start at 5.0 to 0-index bin left of 5.0
    bin_RAZ     = np.arange(15., 195., 15.)
    bin_DOY     = np.arange(8. , 376., 8.0)

    binned_cos_SZA = np.digitize(cos_SZA, bin_cos_SZA, right=True)
    binned_VZA     = np.digitize(VZA    , bin_VZA, right=True)
    binned_RAZ     = np.digitize(RAZ    , bin_RAZ, right=True)
    binned_DOY     = np.digitize(DOY    , bin_DOY, right=True)

    #these datafields' raw values serve as the bins, so no modification needed:
    #Target_Area, land_water_mask, snow_ice_mask, sun_glint_mask, sfc_ID

    #put into array form to serve the whole space
    binned_DOY  = np.ones(shape) * binned_DOY
    Target_Area = np.ones(shape) * Target_Area

    #combine glint and snow-ice mask into sfc_ID
    water = num_land_sfc_types
    sfc_ID[(sun_glint_mask == 0) & (sfc_ID == water)] = num_land_sfc_types + 1
    sfc_ID[snow_ice_mask   == 0]                      = num_land_sfc_types + 2

    observable_level_parameter = np.dstack((binned_cos_SZA ,\
                                            binned_VZA     ,\
                                            binned_RAZ     ,\
                                            Target_Area    ,\
                                            sfc_ID         ,\
                                            binned_DOY     ))

    #find where there is missing data, use SZA as proxy, and give fill val
    missing_idx = np.where(SZA==-999)
    observable_level_parameter[missing_idx[0], missing_idx[1], :] = -999

    observable_level_parameter = observable_level_parameter.astype(dtype=np.int)

    return observable_level_parameter

if __name__ == '__main__':

    import h5py
    import mpi4py.MPI as MPI
    from netCDF4 import Dataset
    import os
    import configparser
    import sys

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    for r in range(size):
        if rank==r:

            config_home_path = '/data/keeling/a/vllgsbr2/c/MAIA_thresh_dev/MAIA_CloudMask_Threshold_Development'
            config = configparser.ConfigParser()
            config.read(config_home_path+'/test_config.txt')

            home     = config['home']['home']
            PTA      = config['current PTA']['PTA']
            PTA_path = config['PTAs'][PTA]

            num_land_SID = int(sys.argv[1])

            #open database to read
            database_path    = '{}/{}/'.format(PTA_path, config['supporting directories']['Database'])
            database_files   = np.sort(os.listdir(database_path))
            database_files   = [database_path + filename for filename in database_files]
            hf_database_path = database_files[r]

            with h5py.File(hf_database_path, 'r') as hf_database:

                #create/open hdf5 file to store observables
                PTA_file_path_OLP = '{}/{}'.format(PTA_path, config['supporting directories']['OLP'])
                hf_OLP_path = '{}/{}_PTA_OLP_start_rank_{:02d}.h5'.format(PTA_file_path_OLP, PTA, rank)

                hf_database_keys = list(hf_database.keys())
                observables = ['WI', 'NDVI', 'NDSI', 'visRef', 'nirRef', 'SVI', 'cirrus']

                with h5py.File(hf_OLP_path, 'w') as hf_OLP:

                    for time_stamp in hf_database_keys:

                        SZA = hf_database[time_stamp+'/sunView_geometry/solarZenith'][()]
                        VZA = hf_database[time_stamp+'/sunView_geometry/sensorZenith'][()]
                        VAA = hf_database[time_stamp+'/sunView_geometry/sensorAzimuth'][()]
                        SAA = hf_database[time_stamp+'/sunView_geometry/solarAzimuth'][()]
                        TA  = int(config['Target Area Integer'][PTA])
                        SIM = hf_database[time_stamp+'/cloud_mask/Snow_Ice_Background_Flag'][()]
                        DOY = int(time_stamp[4:7])

                        bin_DOY    = np.arange(8, 376, 8)
                        binned_DOY = np.digitize(DOY, bin_DOY, right=True)
                        DOY_end    = (binned_DOY+1)*8
                        DOY_end    = '{:03d}'.format(DOY_end)

                        sfc_ID_path  = config['supporting directories']['Surface_IDs']
                        sfc_ID_path  = '{}/{}/num_Kmeans_SID_{:02d}/'.format(PTA_path, sfc_ID_path, num_land_SID)

                        sfc_ID_paths = os.listdir(sfc_ID_path)
                        #find correct sfc ID path for DOY bin
                        sfc_ID_path  = [sfc_ID_path + x for x in sfc_ID_paths \
                                                             if DOY_end in x][0]
                        with Dataset(sfc_ID_path, 'r', format='NETCDF4') as sfc_ID_file:
                            sfc_ID = sfc_ID_file.variables['surface_ID'][:,:]

                        #add one for coast land type (non k Means lan type)
                        num_land_SID += 1
                        SGM = get_sun_glint_mask(SZA, VZA, SAA, VAA, 40, sfc_ID, num_land_SID)
                        get_observable_level_parameter(SZA, VZA, SAA, VAA, Target_Area,\
                                  snow_ice_mask, sfc_ID, DOY, sun_glint_mask,\
                                  num_land_sfc_types)
                        OLP = get_observable_level_parameter(SZA, VZA, SAA, VAA,\
                                TA, SIM, sfc_ID, DOY, SGM, num_land_SID)

                        try:
                            group = hf_OLP.create_group(time_stamp)
                            group.create_dataset('observable_level_paramter',\
                                                  data=OLP, compression='gzip')
                        except:
                            try:
                                group.create_dataset('observable_level_paramter',\
                                                   data=OLP, compression='gzip')
                                hf_OLP[time_stamp+'/observable_level_paramter'][:] = OLP
                            except:
                                hf_OLP[time_stamp+'/observable_level_paramter'][:] = OLP
