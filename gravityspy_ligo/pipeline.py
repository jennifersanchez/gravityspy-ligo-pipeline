from gravityspy_ligo.table import Events
from gravityspy_ligo.utils import utils
from gravityspy_ligo.table.events import id_generator
from sqlalchemy.engine import create_engine
from gravityspy_ligo import __version__
from gwpy.time import tconvert
import argparse
import os
import sys
import socket
import pandas
import math

engine1 = create_engine('postgresql://{0}:{1}@gravityspyplus.ciera.northwestern.edu:5432/gravityspy'.format(os.environ['GRAVITYSPY_DATABASE_USER'],os.environ['GRAVITYSPY_DATABASE_PASSWD']))
### Add logic to auto determine if we are running on LLO or LHO.
hostname = socket.gethostname()
if "ligo-la" in hostname:
    DEFAULT_IFO = "L1"
else:
    DEFAULT_IFO = "H1"

print("Running Gravity Spy pipleine on {0}".format(DEFAULT_IFO))
DEFAULT_START_TIME = math.ceil(pandas.read_sql('SELECT max(event_time) FROM glitches_v2d0 WHERE ifo = \'{0}\''.format(DEFAULT_IFO), engine1).values[0][0])
DEFAULT_STOP_TIME = tconvert('now')

def parse_commandline():
    """Parse the arguments given on the command-line.
    """
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-V', '--version', action='version',
                        version=__version__)
    parser.add_argument("--start-time", type=int,
                        help="Time to start looking for Omicron trigger",
                        default=DEFAULT_START_TIME)
    parser.add_argument("--stop-time", type=int,
                        help="Time to stop looking for Omicron triggers",
                        default=DEFAULT_STOP_TIME)
    parser.add_argument("--project-info-pickle",
                        help="This pickle file ", required=True)
    parser.add_argument("--cnn-model",
                        help="Path to name of cnn model", required=True)
    parser.add_argument("--model-type",
                        help="This can either be `yunan` or `original`", required=True)
    parser.add_argument("--similarity-model",
                        help="Path to name of similarity model",
                        required=True)
    parser.add_argument("--channel-name", help="What channel to check for "
                        "omicron triggers in", required=True)
    parser.add_argument("--frame-type", help="What frame to check for "
                        "omicron triggers in", required=True)
    parser.add_argument("--plot-directory", help="Outdir for images",
                        default='/home/gravityspy/public_html/runs/O4/')
    parser.add_argument("--dqflag", help="What segment to check for "
                        "omicron triggers in",
                        default='DMT-ANALYSIS_READY:1')
    parser.add_argument("--upload", action="store_true", default=False,
                        help="Run without uploading results")
    args = parser.parse_args()


    return args


def main():

    args = parse_commandline()

    # Find new omicron triggers
    trigs = Events.get_triggers(args.start_time, args.stop_time,
                                args.channel_name, dqflag=args.dqflag, snr_min=7.5)

    if trigs.to_pandas().empty:
        return

    # Make q transforms and label the images
    trigs_results = trigs.classify(path_to_cnn=args.cnn_model,
                                   plot_directory=args.plot_directory,
                                   channel_name=args.channel_name,
                                   frametype=args.frame_type,
                                   model_type=args.model_type,
                                   nproc=20)

    all_spectrogram_files = []
    all_spectrogram_files.extend(list(trigs_results['Filename1']))
    all_spectrogram_files.extend(list(trigs_results['Filename2']))
    all_spectrogram_files.extend(list(trigs_results['Filename3']))
    all_spectrogram_files.extend(list(trigs_results['Filename4']))

    # extract the features from the q_transforms.
    features = utils.get_features(filenames_of_images_to_classify=all_spectrogram_files,
                                  path_to_semantic_model=args.similarity_model)
    features['ifo'] = args.channel_name.split(':')[0]

    # Determine based on ml scores what level these images should go to
    trigs_results.determine_workflow_and_subjectset(project_info_pickle=args.project_info_pickle)

    if args.upload:
        # upload them based on this information
        trigs_results.upload_to_zooniverse()

    # Find the links_subjects after upload and add them to the features table
    subject_ids = trigs_results.to_pandas().loc[trigs_results.to_pandas().gravityspy_id.isin(features.to_pandas().gravityspy_id), 'links_subjects'].values
    event_times = trigs_results.to_pandas().loc[trigs_results.to_pandas().gravityspy_id.isin(features.to_pandas().gravityspy_id), 'event_time'].values
    features['links_subjects'] = subject_ids
    features['event_time'] = event_times
    features = Events(features)

    # convert objects to unicode string for upload to sql table
    for col in trigs_results.itercols():
        if col.dtype.kind in 'O':
            trigs_results.replace_column(col.name, col.astype('str'))

    if args.upload:
        trigs_results.to_sql(table="glitches_v2d0")
        features.to_sql(table='similarity_index_o3')

    SQL_USER = os.environ['SQL_USER']
    SQL_PASS = os.environ['SQL_PASS']
    engine = create_engine('mysql://{0}:{1}@127.0.0.1:33060/gravityspy'.format(SQL_USER,SQL_PASS))
    if args.upload:
        trigs_results.to_glitch_db(table='GSMetadata', engine=engine)
