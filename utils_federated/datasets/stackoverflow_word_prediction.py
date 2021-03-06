# Copyright 2019, Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Data loader for Stack Overflow next-word-prediction tasks."""

import collections
import hashlib
from typing import Any, Callable, Dict, List, Optional, Tuple

import attr
import numpy as np
import tensorflow as tf
import tensorflow_federated as tff

EVAL_BATCH_SIZE = 100


@attr.s(eq=False, frozen=True)
class SpecialTokens(object):
  """Structure for Special tokens.

  Attributes:
    pad: int - Special token for padding.
    oov: list - Special tokens for out of vocabulary tokens.
    bos: int - Special token for beginning of sentence.
    eos: int - Special token for end of sentence.
  """
  pad = attr.ib()
  oov = attr.ib()
  bos = attr.ib()
  eos = attr.ib()


def create_vocab(vocab_size: int) -> List[str]:
  """Creates vocab from `vocab_size` most common words in Stackoverflow."""
  vocab_dict = tff.simulation.datasets.stackoverflow.load_word_counts()
  return list(vocab_dict.keys())[:vocab_size]


def split_input_target(chunk: tf.Tensor) -> Tuple[tf.Tensor, tf.Tensor]:
  """Generate input and target data.

  The task of language model is to predict the next word.

  Args:
    chunk: A Tensor of text data.

  Returns:
    A tuple of input and target data.
  """
  input_text = tf.map_fn(lambda x: x[:-1], chunk)
  target_text = tf.map_fn(lambda x: x[1:], chunk)
  return (input_text, target_text)


def build_to_ids_fn(
    vocab: List[str],
    max_sequence_length: int,
    num_oov_buckets: int = 1) -> Callable[[tf.Tensor], tf.Tensor]:
  """Constructs function mapping examples to sequences of token indices."""
  special_tokens = get_special_tokens(len(vocab), num_oov_buckets)
  bos = special_tokens.bos
  eos = special_tokens.eos

  table_values = np.arange(len(vocab), dtype=np.int64)
  table = tf.lookup.StaticVocabularyTable(
      tf.lookup.KeyValueTensorInitializer(vocab, table_values),
      num_oov_buckets=num_oov_buckets)

  def to_ids(example):

    sentence = tf.reshape(example['tokens'], shape=[1])
    words = tf.strings.split(sentence, sep=' ').values
    truncated_words = words[:max_sequence_length]
    tokens = table.lookup(truncated_words) + 1
    tokens = tf.cond(
        tf.less(tf.size(tokens), max_sequence_length),
        lambda: tf.concat([tokens, [eos]], 0), lambda: tokens)

    return tf.concat([[bos], tokens], 0)

  return to_ids


def batch_and_split(dataset: tf.data.Dataset, max_sequence_length: int,
                    batch_size: int) -> tf.data.Dataset:
  return dataset.padded_batch(
      batch_size, padded_shapes=[max_sequence_length + 1]).map(
          split_input_target, num_parallel_calls=tf.data.experimental.AUTOTUNE)


def get_special_tokens(vocab_size: int,
                       num_oov_buckets: int = 1) -> SpecialTokens:
  """Gets tokens dataset preprocessing code will add to Stackoverflow."""
  return SpecialTokens(
      pad=0,
      oov=[vocab_size + 1 + n for n in range(num_oov_buckets)],
      bos=vocab_size + num_oov_buckets + 1,
      eos=vocab_size + num_oov_buckets + 2)


def create_preprocess_fn(
    vocab: List[str],
    num_oov_buckets: int,
    client_batch_size: int,
    client_epochs_per_round: int,
    max_sequence_length: int,
    max_elements_per_client: int,
    max_shuffle_buffer_size: int = 10000) -> tff.Computation:
  """Creates a preprocessing functions for Stack Overflow next-word-prediction.

  This function returns a `tff.Computation` which takes a dataset and returns a
  dataset, suitable for mapping over a set of unprocessed client datasets.

  Args:
    vocab: Vocabulary which defines the embedding.
    num_oov_buckets: The number of out of vocabulary buckets. Tokens that are
      not present in the `vocab` are hashed into one of these buckets.
    client_batch_size: Integer representing batch size to use on the clients.
    client_epochs_per_round: Number of epochs for which to repeat train client
      dataset. Must be a positive integer.
    max_sequence_length: Integer determining shape of padded batches. Sequences
      will be padded up to this length, and sentences longer than this will be
      truncated to this length.
    max_elements_per_client: Integer controlling the maximum number of elements
      to take per client. If -1, keeps all elements for each client. This is
      applied before repeating `client_epochs_per_round`, and is intended
      primarily to contend with the small set of clients with tens of thousands
      of examples.
    max_shuffle_buffer_size: Maximum shuffle buffer size.

  Returns:
    A `tff.Computation` taking as input a `tf.data.Dataset`, and returning a
    `tf.data.Dataset` formed by preprocessing according to the input arguments.
  """
  if client_batch_size <= 0:
    raise ValueError('client_batch_size must be a positive integer. You have '
                     'passed {}.'.format(client_batch_size))
  elif client_epochs_per_round <= 0:
    raise ValueError('client_epochs_per_round must be a positive integer. '
                     'You have passed {}.'.format(client_epochs_per_round))
  elif max_sequence_length <= 0:
    raise ValueError('max_sequence_length must be a positive integer. You have '
                     'passed {}.'.format(max_sequence_length))
  elif max_elements_per_client == 0 or max_elements_per_client < -1:
    raise ValueError(
        'max_elements_per_client must be a positive integer or -1. You have '
        'passed {}.'.format(max_elements_per_client))
  if num_oov_buckets <= 0:
    raise ValueError('num_oov_buckets must be a positive integer. You have '
                     'passed {}.'.format(num_oov_buckets))

  if (max_elements_per_client == -1 or
      max_elements_per_client > max_shuffle_buffer_size):
    shuffle_buffer_size = max_shuffle_buffer_size
  else:
    shuffle_buffer_size = max_elements_per_client

  # Features are intentionally sorted lexicographically by key for consistency
  # across datasets.
  feature_dtypes = collections.OrderedDict(
      creation_date=tf.string,
      score=tf.int64,
      tags=tf.string,
      title=tf.string,
      tokens=tf.string,
      type=tf.string,
  )

  @tff.tf_computation(tff.SequenceType(feature_dtypes))
  def preprocess_fn(dataset):
    to_ids = build_to_ids_fn(
        vocab=vocab,
        max_sequence_length=max_sequence_length,
        num_oov_buckets=num_oov_buckets)
    dataset = dataset.take(max_elements_per_client).shuffle(
        shuffle_buffer_size).repeat(client_epochs_per_round).map(
            to_ids, num_parallel_calls=tf.data.experimental.AUTOTUNE)
    return batch_and_split(dataset, max_sequence_length, client_batch_size)

  return preprocess_fn


def get_federated_datasets(
    vocab_size: int,
    max_sequence_length: int,
    num_oov_buckets: int = 1,
    train_client_batch_size: int = 16,
    test_client_batch_size: int = 100,
    train_client_epochs_per_round: int = 1,
    test_client_epochs_per_round: int = 1,
    max_elements_per_train_client: int = 1000,
    max_elements_per_test_client: int = -1,
    train_shuffle_buffer_size: int = 10000,
    test_shuffle_buffer_size: int = 1,
    train_transform: Optional[Callable[[str, int], Callable[[Any],
                                                            Any]]] = None,
) -> Tuple[tff.simulation.datasets.ClientData,
           tff.simulation.datasets.ClientData]:
  """Loads federated Stack Overflow next-word prediction datasets.

  This function ignores the heldout Stack Overflow dataset for consistency with
  "Adaptive Federated Optimization".

  Args:
    vocab_size: Integer representing size of the vocab to use. Vocabulary will
      then be the `vocab_size` most frequent words in the Stackoverflow dataset.
    max_sequence_length: Integer determining the shape of the padded batches in
      each client dataset. Sequences will be padded up to this length, and
      sequences longer than `max_sequence_len` will be truncated to this length.
    num_oov_buckets: Number of out of vocabulary buckets.
    train_client_batch_size: The batch size for all train clients.
    test_client_batch_size: The batch size for all test clients.
    train_client_epochs_per_round: The number of epochs each train client should
      iterate over their local dataset, via `tf.data.Dataset.repeat`. Must be a
      positive integer.
    test_client_epochs_per_round: The number of epochs each test client should
      iterate over their local dataset, via `tf.data.Dataset.repeat`. Must be a
      positive integer.
    max_elements_per_train_client: Integer controlling the maximum number of
      elements to take per client. If -1, keeps all elements for each training
      client.
    max_elements_per_test_client: Integer controlling the maximum number of
      elements to take per client. If -1, keeps all elements for each test
      client.
    train_shuffle_buffer_size: An integer representing the shuffle buffer size
      (as in `tf.data.Dataset.shuffle`) for each train client's dataset. If set
      to some integer less than or equal to 1, no shuffling occurs.
    test_shuffle_buffer_size: An integer representing the shuffle buffer size
      (as in `tf.data.Dataset.shuffle`) for each test client's dataset. If set
      to some integer less than or equal to 1, no shuffling occurs.
    train_transform: An optional transformation to perform on the training data.
      For example, to get a transformation that inserts random secrets into the
      data, use `secret_inserting_transform_fn`.

  Returns:
    A tuple (stackoverflow_train, stackoverflow_test) of
    `tff.simulation.datasets.ClientData` instances representing the federated
    training and test datasets.
  """
  if vocab_size <= 0:
    raise ValueError('vocab_size must be a positive integer; you have '
                     'passed {}'.format(vocab_size))
  if train_shuffle_buffer_size <= 1:
    train_shuffle_buffer_size = 1
  if test_shuffle_buffer_size <= 1:
    test_shuffle_buffer_size = 1

  (stackoverflow_train, _,
   stackoverflow_test) = tff.simulation.datasets.stackoverflow.load_data()

  if train_transform:
    stackoverflow_train = tff.simulation.datasets.TransformingClientData(
        stackoverflow_train, train_transform)

  vocab = create_vocab(vocab_size)

  preprocess_train_fn = create_preprocess_fn(
      vocab=vocab,
      num_oov_buckets=num_oov_buckets,
      client_batch_size=train_client_batch_size,
      client_epochs_per_round=train_client_epochs_per_round,
      max_sequence_length=max_sequence_length,
      max_elements_per_client=max_elements_per_train_client,
      max_shuffle_buffer_size=train_shuffle_buffer_size)
  stackoverflow_train = stackoverflow_train.preprocess(preprocess_train_fn)

  preprocess_test_fn = create_preprocess_fn(
      vocab=vocab,
      num_oov_buckets=num_oov_buckets,
      client_batch_size=test_client_batch_size,
      client_epochs_per_round=test_client_epochs_per_round,
      max_sequence_length=max_sequence_length,
      max_elements_per_client=max_elements_per_test_client,
      max_shuffle_buffer_size=test_shuffle_buffer_size)
  stackoverflow_test = stackoverflow_test.preprocess(preprocess_test_fn)

  return stackoverflow_train, stackoverflow_test


def get_centralized_datasets(
    vocab_size: int,
    max_sequence_length: int,
    train_batch_size: int = 16,
    validation_batch_size: int = 100,
    test_batch_size: int = 100,
    num_validation_examples: int = 10000,
    train_shuffle_buffer_size: int = 10000,
    validation_shuffle_buffer_size: int = 1,
    test_shuffle_buffer_size: int = 1,
    num_oov_buckets: int = 1
) -> Tuple[tf.data.Dataset, tf.data.Dataset, tf.data.Dataset]:
  """Creates centralized datasets for Stack Overflow NWP.

  Args:
    vocab_size: Integer representing size of the vocab to use. Vocabulary will
      then be the `vocab_size` most frequent words in the Stackoverflow dataset.
    max_sequence_length: Integer determining shape of padded batches. Sequences
      will be padded up to this length, and sentences longer than
      `max_sequence_length` will be truncated to this length.
    train_batch_size: The batch size for the training dataset.
    validation_batch_size: The batch size for the validation dataset.
    test_batch_size: The batch size for the test dataset.
    num_validation_examples: Number of examples from Stackoverflow test set to
      use for validation on each round.
    train_shuffle_buffer_size: The shuffle buffer size for the training dataset.
      If set to a number <= 1, no shuffling occurs.
    validation_shuffle_buffer_size: The shuffle buffer size for the validation
      dataset. If set to a number <= 1, no shuffling occurs.
    test_shuffle_buffer_size: The shuffle buffer size for the training dataset.
      If set to a number <= 1, no shuffling occurs.
    num_oov_buckets: Number of out of vocabulary buckets.

  Returns:
    train_dataset: A `tf.data.Dataset` instance representing the training
      dataset.
    validation_dataset: A `tf.data.Dataset` instance representing the validation
      dataset.
    test_dataset: A `tf.data.Dataset` instance representing the test dataset.
  """

  vocab = create_vocab(vocab_size)
  train_preprocess_fn = create_preprocess_fn(
      vocab=vocab,
      num_oov_buckets=num_oov_buckets,
      client_batch_size=train_batch_size,
      client_epochs_per_round=1,
      max_sequence_length=max_sequence_length,
      max_elements_per_client=-1,
      max_shuffle_buffer_size=train_shuffle_buffer_size)

  validation_preprocess_fn = create_preprocess_fn(
      vocab=vocab,
      num_oov_buckets=num_oov_buckets,
      client_batch_size=validation_batch_size,
      client_epochs_per_round=1,
      max_sequence_length=max_sequence_length,
      max_elements_per_client=-1,
      max_shuffle_buffer_size=validation_shuffle_buffer_size)

  test_preprocess_fn = create_preprocess_fn(
      vocab=vocab,
      num_oov_buckets=num_oov_buckets,
      client_batch_size=test_batch_size,
      client_epochs_per_round=1,
      max_sequence_length=max_sequence_length,
      max_elements_per_client=-1,
      max_shuffle_buffer_size=test_shuffle_buffer_size)

  raw_train, _, raw_test = tff.simulation.datasets.stackoverflow.load_data()
  stackoverflow_train = raw_train.create_tf_dataset_from_all_clients()
  stackoverflow_train = train_preprocess_fn(stackoverflow_train)

  test_and_val_dataset = raw_test.create_tf_dataset_from_all_clients()

  stackoverflow_validation = test_and_val_dataset.take(num_validation_examples)
  stackoverflow_validation = validation_preprocess_fn(stackoverflow_validation)

  stackoverflow_test = test_and_val_dataset.skip(num_validation_examples)
  stackoverflow_test = test_preprocess_fn(stackoverflow_test)

  return stackoverflow_train, stackoverflow_validation, stackoverflow_test


def make_random_secrets(vocab_size: int,
                        num_secrets: int,
                        secret_len: int,
                        seed: int = 0):
  vocab = create_vocab(vocab_size)
  np.random.seed(seed)
  return [
      ' '.join(np.random.choice(vocab, secret_len)) for _ in range(num_secrets)
  ]


def secret_inserting_transform_fn(
    client_ids: List[str],
    secrets: Dict[str, Tuple[int, float]],
    seed: int = 0) -> Callable[[str, int], Callable[[Any], Any]]:
  """Builds secret inserting transform_fn for `TransformingClientData`.

  Assigns secret phrases to some clients. If a client is assigned a secret, each
  of that client's examples will be selected independently at random for
  replacement, in which case the `tokens` field of the example will be replaced
  by the secret.

  It is assumed that this will be used in a `TransformingClientData` with
  `num_transformed_clients == len(client_ids)` so the `index` argument of
  the transform_fn must be zero.

  The method is similar to that used by Thakkar et. al (2020)
  https://arxiv.org/abs/2006.07490 except a deterministic number of clients
  are selected for each secret.

  Args:
    client_ids: A list of all client IDs.
    secrets: A dict mapping secrets of type `str` to an (int, float) 2-tuple.
      The int is the number of clients that will have that secret inserted, and
      the float is the probability that any given example of a selected client
      will be replaced with that client's secret (p_e in Thakkar et. al (2020)).
    seed: Random seed for client and example selection.

  Returns:
    A function that can be passed to the initializer of TransformingClientData
    to insert secrets.
  """

  if (not secrets or not isinstance(secrets, dict) or
      not all([isinstance(secret, str) for secret in secrets])):
    raise ValueError('`secrets` must be a non-zero length dict with str keys.')

  if any(value[0] <= 0 for value in secrets.values()):
    raise ValueError('Client count for each secret must be positive.')

  if any(not 0 < value[1] <= 1 for value in secrets.values()):
    raise ValueError('p_e values must be valid probabilities in (0, 1].')

  if sum(cc for (cc, _) in secrets.values()) >= len(client_ids):
    raise ValueError(
        'Client counts cannot sum to more than total number of clients.')

  np.random.seed(seed)
  id_perm = np.random.permutation(client_ids)
  id_to_secret = {}
  i = 0
  for secret, (client_count, p) in secrets.items():
    for _ in range(client_count):
      id_to_secret[id_perm[i]] = (secret, p)
      i += 1

  def make_transform_fn(client_id: str, index: int):
    if index:
      raise ValueError(
          'secret_inserting_transform_fn is intended to be used in a '
          '`TransformingClientData` with `num_transformed_clients == '
          'len(client_ids)`. `index` should therefore always be zero.')

    secret_and_prob = id_to_secret.get(client_id)
    if not secret_and_prob:
      return None

    client_hash = hashlib.md5(client_id.encode()).digest()
    # Hash is in bytes, so convert to int for numpy seed.
    client_seed = (int.from_bytes(client_hash, 'big') + seed) % (2**32)

    secret, p_e = secret_and_prob

    def transform_fn(example):
      example_seed = tf.strings.to_hash_bucket_fast(example['creation_date'],
                                                    2**32)
      uniform = tf.random.stateless_uniform(
          (),
          [tf.cast(client_seed, tf.uint32),
           tf.cast(example_seed, tf.uint32)])
      if uniform < p_e:
        example['tokens'] = secret
      return example

    return transform_fn

  return make_transform_fn
