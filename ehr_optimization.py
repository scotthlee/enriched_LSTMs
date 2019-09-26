import pandas as pd
import numpy as np
import h5py
import GPy, GPyOpt

from keras import regularizers
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.models import load_model
from sklearn.model_selection import train_test_split
from scipy.sparse import load_npz

import metrics.classification as mc
from models.supervised import EnrichedRNN

'''
Data import and splitting
'''
# Importing the integer sequences
indir = 'C:/data/syndromic/asthma/'
outdir = 'data/asthma/hp_optimization/'
int_sents = h5py.File(indir + 'word_sents.hdf5', mode='r')
X = np.array(int_sents['sents'])
int_sents.close()

# Importing the sparse records and targets
sparse_records = load_npz(indir + 'sparse_records.npz')
records = pd.read_csv(indir + 'records_clipped.csv')

# Setting the target for classification
target_conditions = ['asthma', 'flu', 'vom', 'alc', 'upper_resp', 'allergy']
target_codes = ['128', '123', '250', '242', '660', '126', '253']

# Importing the vocabulary
vocab_df = pd.read_csv(indir + 'word_dict.csv')
vocab = dict(zip(vocab_df.word, vocab_df.value))

# Splitting the data into training, validation, and test sets
n_range = range(X.shape[0])
seed = 10221983

for code in target_codes:
    y = np.array([code in doc for doc in records.ccs], dtype=np.uint8)
    
    # Splitting the data into training, validation, and test sets
    train, not_train = train_test_split(list(range(X.shape[0])),
                                        test_size=.5,
                                        stratify=y,
                                        random_state=seed)
    val, test = train_test_split(not_train,
                                 test_size=.3,
                                 stratify=y[not_train],
                                 random_state=seed)

    '''
    Setting up the hyperparameters
    '''
    # Values for the fixed hyperparameters
    train_batch = 512
    pred_batch = 512
    vocab_size = len(vocab.keys())
    max_length = X.shape[1]
    sparse_size = sparse_records.shape[1]
    epochs = 25
    opt_iter = 20

    # Takes a set of hyperparameters and returns the best validation loss
    def evaluate_hps(e_drop,
                     r_drop,
                     e_size,
                     r_size):

        # Instantiating, fitting, and validating the model
        modfile = outdir + code + '_opt_ehr.hdf5'
        check = ModelCheckpoint(filepath=modfile,
                                save_best_only=True,
                                verbose=1)
        stop = EarlyStopping(monitor='val_loss',
                             patience=1)
        mod = EnrichedRNN(sparse_size,
                          vocab_size,
                          max_length,
                          output_size=1,
                          embedding_size=e_size,
                          hidden_size=r_size,
                          embeddings_dropout=e_drop,
                          recurrent_dropout=r_drop)
        mod.compile(optimizer='adam',
                    loss='binary_crossentropy')
        fit = mod.fit([sparse_records[train], X[train]], y[train],
                      batch_size=train_batch,
                      epochs=epochs,
                      verbose=1,
                      callbacks=[check, stop],
                      validation_data=([[sparse_records[val], X[val]], y[val]]))
        score = 100 * np.min(fit.history['val_loss'])
        return score

    # Bounds for the GP optimizer
    bounds = [{'name': 'e_drop',
               'type': 'discrete',
               'domain': (0.0, 0.25, 0.5, 0.75, 0.85)},
              {'name': 'r_drop',
               'type': 'discrete',
               'domain': (0.0, 0.25, 0.5, 0.75, 0.85)},
              {'name': 'e_size',
               'type': 'discrete',
               'domain': (64, 128, 256, 512)},
              {'name': 'r_size',
               'type': 'discrete',
               'domain': (64, 128, 256, 512)}
              ]

    # Function for GPyOpt to optimize
    def f(x):
        print(x)
        eval = evaluate_hps(e_drop=float(x[:, 0]),
                            r_drop=float(x[:, 1]),
                            e_size=int(x[:, 2]),
                            r_size=int(x[:, 3]))
        pd.Series(eval.flatten()).to_csv(outdir + str(x) + '.csv')
        return eval

    # Running the optimization
    opt_rnn = GPyOpt.methods.BayesianOptimization(f=f,
                                                  num_cores=20,
                                                  domain=bounds,
                                                  initial_design_numdata=10)
    opt_rnn.run_optimization(opt_iter)
    pd.Series(opt_rnn.x_opt).to_csv(outdir + code + '_best_ehr_params.csv', 
                                    index=False)
