from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import tensorflow.contrib.slim as slim

FLAGS = tf.app.flags.FLAGS


# Batch normalization. Constant governing the exponential moving average of
# the 'global' mean and variance for all activations.
BATCHNORM_MOVING_AVERAGE_DECAY = 0.9997


def vgg_16(inputs,
           num_classes=1000,
           is_training=True,
           dropout_keep_prob=0.5,
           spatial_squeeze=True,
           scope='vgg_16'):
  """Oxford Net VGG 16-Layers version D Example.

  Note: All the fully_connected layers have been transformed to conv2d layers.
        To use in classification mode, resize input to 224x224.

  Args:
    inputs: a tensor of size [batch_size, height, width, channels].
    num_classes: number of predicted classes.
    is_training: whether or not the model is being trained.
    dropout_keep_prob: the probability that activations are kept in the dropout
      layers during training.
    spatial_squeeze: whether or not should squeeze the spatial dimensions of the
      outputs. Useful to remove unnecessary dimensions for classification.
    scope: Optional scope for the variables.

  Returns:
    the last op containing the log predictions and end_points dict.
  """
  with tf.name_scope(scope, 'vgg_16', [inputs]) as sc:
    end_points_collection = sc + '_end_points'
    # Collect outputs for conv2d, fully_connected and max_pool2d.
    with slim.arg_scope([slim.conv2d, slim.fully_connected, slim.max_pool2d],
                        outputs_collections=end_points_collection):
      net = slim.repeat(inputs, 2, slim.conv2d, 64, [3, 3], scope='conv1')
      net = slim.max_pool2d(net, [2, 2], scope='pool1')
      net = slim.repeat(net, 2, slim.conv2d, 128, [3, 3], scope='conv2')
      net = slim.max_pool2d(net, [2, 2], scope='pool2')
      net = slim.repeat(net, 3, slim.conv2d, 256, [3, 3], scope='conv3')
      net = slim.max_pool2d(net, [2, 2], scope='pool3')
      net = slim.repeat(net, 3, slim.conv2d, 512, [3, 3], scope='conv4')
      net = slim.max_pool2d(net, [2, 2], scope='pool4')
      net = slim.repeat(net, 3, slim.conv2d, 512, [3, 3], scope='conv5')
      net = slim.max_pool2d(net, [2, 2], scope='pool5')
      # Use conv2d instead of fully_connected layers.
      net = slim.conv2d(net, 4096, [3, 3], padding='VALID', scope='fc6')
      net = slim.dropout(net, dropout_keep_prob, is_training=is_training,
                         scope='dropout6')
      net = slim.conv2d(net, 4096, [1, 1], scope='fc7')
      net = slim.dropout(net, dropout_keep_prob, is_training=is_training,
                         scope='dropout7')
      net = slim.conv2d(net, num_classes, [1, 1],
                        activation_fn=None,
                        normalizer_fn=None,
                        scope='fc8')
      # Convert end_points_collection into a end_point dict.
      end_points = slim.utils.convert_collection_to_dict(end_points_collection)
      if spatial_squeeze:
        net = tf.squeeze(net, [1, 2], name='fc8/squeezed')
        end_points[sc + '/fc8'] = net
      return net, end_points


def inference(images, num_classes, is_training=True, scope='vgg_16'):
    """Build Inception v3 model architecture.

     See here for reference: http://arxiv.org/abs/1512.00567

    Args:
        images: Images returned from inputs() or distorted_inputs().
        num_classes: number of classes
        for_training: If set to `True`, build the inference model for training.
        Kernels that operate differently for inference during training
        e.g. dropout, are appropriately configured.
        restore_logits: whether or not the logits layers should be restored.
        Useful for fine-tuning a model with different num_classes.
        scope: optional prefix string identifying the ImageNet tower.

    Returns:
        Logits. 2-D float Tensor.
        Auxiliary Logits. 2-D float Tensor of side-head. Used for training only.
    """
    # Parameters for BatchNorm.
    batch_norm_params = {
        # Decay for the moving averages.
        'decay': BATCHNORM_MOVING_AVERAGE_DECAY,
        # epsilon to prevent 0s in variance.
        'epsilon': 0.001,
        # calculate moving average or using exist one
        'is_training': is_training
    }
    # Set weight_decay for weights in Conv and FC layers.
    with slim.arg_scope([slim.conv2d, slim.fully_connected],
                        weights_regularizer=slim.l2_regularizer(FLAGS.weight_decay)):
        with slim.arg_scope([slim.conv2d],
                            weights_initializer=slim.variance_scaling_initializer(),
                            activation_fn=tf.nn.relu,
                            normalizer_fn=slim.batch_norm,
                            normalizer_params=batch_norm_params):
            logits, endpoints = vgg_16(
                images,
                num_classes=num_classes,
                dropout_keep_prob=0.8,
                is_training=is_training,
                scope=scope
            )

    # Add summaries for viewing model statistics on TensorBoard.
    _activation_summaries(endpoints)

    return logits

def loss(logits, labels):
    """Adds all losses for the model.

  Note the final loss is not returned. Instead, the list of losses are collected
  by slim.losses. The losses are accumulated in tower_loss() and summed to
  calculate the total loss.

  Args:
    logits: List of logits from inference(). Each entry is a 2-D float Tensor.
    labels: Labels from distorted_inputs or inputs(). 1-D tensor
            of shape [batch_size]
  """
    # Reshape the labels into a dense Tensor of
    # shape [FLAGS.batch_size, num_classes].
    with tf.name_scope("train_loss"):
        # cal softmax loss
        num_classes = logits[0].get_shape()[-1].value
        onehot_labels = tf.one_hot(indices=tf.cast(labels, tf.int32), depth=num_classes)
        softmax_loss = tf.losses.softmax_cross_entropy(onehot_labels=onehot_labels,
                                                       logits=logits,
                                                       label_smoothing=FLAGS.label_smoothing,
                                                       scope='softmax_loss')
        tf.summary.scalar('softmax_loss', softmax_loss)

        # cal regular loss
        regularization_loss = tf.add_n(tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES))
        tf.summary.scalar('train_regular_loss', regularization_loss)

        # cal total loss
        total_loss = softmax_loss + regularization_loss
        tf.summary.scalar('train_total_loss', total_loss)
        return total_loss


def _activation_summary(x):
    """Helper to create summaries for activations.

    Creates a summary that provides a histogram of activations.
    Creates a summary that measure the sparsity of activations.

    Args:
      x: Tensor
    """
    # session. This helps the clarity of presentation on tensorboard.
    tf.summary.histogram(x.op.name + '/activations', x)
    tf.summary.scalar(x.op.name + '/sparsity', tf.nn.zero_fraction(x))


def _activation_summaries(endpoints):
    with tf.name_scope('summaries'):
        for act in endpoints.values():
            _activation_summary(act)

