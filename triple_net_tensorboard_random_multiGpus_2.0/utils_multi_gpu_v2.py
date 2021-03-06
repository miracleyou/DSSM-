#-*- coding:utf-8 -*-
import pandas as pd
import random
import time
import numpy as np
import tensorflow as tf

'''
the main part of the code：
+ layer of dssm
+ sess feed_dict function
+ tools of summary
'''

#**************************************summary***********************************************
def variable_summaries(var, name):
    """Attach a lot of summaries to a Tensor."""
    with tf.name_scope('summaries'):
        mean = tf.reduce_mean(var)
        tf.summary.scalar('mean/' + name, mean)
        with tf.name_scope('stddev'):
            stddev = tf.sqrt(tf.reduce_sum(tf.square(var - mean)))
        tf.summary.scalar('sttdev/' + name, stddev)
        tf.summary.scalar('max/' + name, tf.reduce_max(var))
        tf.summary.scalar('min/' + name, tf.reduce_min(var))
        tf.summary.histogram(name, var)
        
def get_text_summaries():
    """
    desribe:this summary should not be merged
    """
    with tf.name_scope('predict_text'):
        predict_strings = tf.placeholder(tf.string,name='predict')
        text_summary = tf.summary.text(name='pair',tensor=predict_strings)
    return predict_strings,text_summary
    

def get_evaluate_test_summary():
    """
    desribe:this summary should not be merged
    """
    with tf.name_scope('evaluate'):
        evaluate_on_test_acc = tf.placeholder(tf.float32,name='evaluateOnTest')
        return evaluate_on_test_acc,tf.summary.scalar('evaluate_on_test',evaluate_on_test_acc)

def get_evaluate_train_summary():
    """
    desribe:this summary should not be merged
    """
    with tf.name_scope('evaluate'):
        evaluate_on_test_acc = tf.placeholder(tf.float32,name='evaluateOnTrain')
        return evaluate_on_test_acc,tf.summary.scalar('evaluate_on_train',evaluate_on_test_acc)
   
 #**************************************layer***********************************************

def batch_normalization(x, phase_train, out_size):
    """
    Batch normalization on convolutional maps.
    Ref.: http://stackoverflow.com/questions/33949786/how-could-i-use-batch-normalization-in-tensorflow
    Args:
        x:           Tensor, 4D BHWD input maps
        out_size:       integer, depth of input maps
        phase_train: boolean tf.Varialbe, true indicates training phase
        scope:       string, variable scope
    Return:
        normed:      batch-normalized maps
    """
    with tf.variable_scope('bn'):
        beta = tf.Variable(tf.constant(0.0, shape=[out_size]),
                           name='beta', trainable=True)
        gamma = tf.Variable(tf.constant(1.0, shape=[out_size]),
                            name='gamma', trainable=True)
        batch_mean, batch_var = tf.nn.moments(x, [0], name='moments')
        ema = tf.train.ExponentialMovingAverage(decay=0.5)

        def mean_var_with_update():
            ema_apply_op = ema.apply([batch_mean, batch_var])
            with tf.control_dependencies([ema_apply_op]):
                return tf.identity(batch_mean), tf.identity(batch_var)

        mean, var = tf.cond(phase_train,
                            mean_var_with_update,
                            lambda: (ema.average(batch_mean), ema.average(batch_var)))
        normed = tf.nn.batch_normalization(x, mean, var, beta, gamma, 1e-3)
    return normed

def input_layer(input_len):
    with tf.name_scope('input'):
        query_in = tf.sparse_placeholder(tf.float32, shape=[None, input_len], name='QueryBatch')
        doc_positive_in = tf.sparse_placeholder(tf.float32, shape=[None, input_len], name='DocBatch')
        doc_negative_in = tf.sparse_placeholder(tf.float32, shape=[None, input_len], name='DocBatch')
        on_train = tf.placeholder(tf.bool)
    return query_in,doc_positive_in,doc_negative_in,on_train

def batch_layer(query,doc_pos,doc_neg,next_layer_len,on_train,name):
    with tf.name_scope(name):
        query_layer = batch_normalization(query, on_train, next_layer_len)
        doc_positive_layer = batch_normalization(doc_pos, on_train, next_layer_len)
        doc_negative_layer = batch_normalization(doc_neg, on_train, next_layer_len)

        query_layer_out = tf.nn.relu(query_layer)
        doc_positive_layer_out = tf.nn.relu(doc_positive_layer)
        doc_negative_layer_out = tf.nn.relu(doc_negative_layer)
    return query_layer_out,doc_positive_layer_out,doc_negative_layer_out

def fc_layer(query,doc_positive,doc_negative,layer_in_len,layer_out_len,name,first_layer,batch_norm,is_first):
    with tf.variable_scope(name):
        layer_par_range = np.sqrt(6.0 / (layer_in_len + layer_out_len))
        weight = tf.get_variable(name='weights',initializer=tf.random_uniform([layer_in_len, layer_out_len], -layer_par_range, layer_par_range))
        bias = tf.get_variable(name="biases",initializer=tf.random_uniform([layer_out_len], -layer_par_range, layer_par_range))
        if is_first:
            variable_summaries(weight, 'weights')
            variable_summaries(bias, 'biases')
        
        if first_layer:
            query_out = tf.sparse_tensor_dense_matmul(query, weight) + bias
            doc_positive_out = tf.sparse_tensor_dense_matmul(doc_positive, weight) + bias
            doc_negative_out = tf.sparse_tensor_dense_matmul(doc_negative, weight) + bias
        else:
            query_out = tf.matmul(query, weight) + bias
            doc_positive_out = tf.matmul(doc_positive, weight) + bias
            doc_negative_out = tf.matmul(doc_negative, weight) + bias
        
        if batch_norm:
            query_out,doc_positive_out,doc_negative_out = batch_layer(query_out,doc_positive_out,doc_negative_out,layer_out_len,tf.convert_to_tensor(True),name+'BN')
    return query_out,doc_positive_out,doc_negative_out

    
def cos_distance_layer(query_y,doc_positive_y, doc_negative_y,doc_negative_num,batch_size):
    with tf.name_scope('Cosine_distance'):
    
        doc_y = tf.concat([doc_positive_y, doc_negative_y], axis=0)

        query_norm = tf.tile(tf.sqrt(tf.reduce_sum(tf.square(query_y), 1, True)), [doc_negative_num+1, 1])
        doc_norm = tf.sqrt(tf.reduce_sum(tf.square(doc_y), 1, True))

        prod = tf.reduce_sum(tf.multiply(tf.tile(query_y, [doc_negative_num+1, 1]), doc_y), 1, True)
        norm_prod = tf.multiply(query_norm, doc_norm)

        # cos_sim_raw = query * doc / (||query|| * ||doc||)
        cos_sim_raw = tf.truediv(prod, norm_prod)
        cos_sim = tf.transpose(tf.reshape(tf.transpose(cos_sim_raw), [doc_negative_num+1, batch_size]))  * 20
    return cos_sim

def eular_distance_layer(query_y,doc_positive_y, doc_negative_y,doc_negative_num,batch_size):
    with tf.name_scope('Eular_distance'):
        doc_y = tf.concat([doc_positive_y, doc_negative_y], axis=0)
        eular_distance_raw = tf.reduce_sum(tf.square(tf.tile(query_y, [doc_negative_num+1, 1]) - doc_y), 1)
        eular_distance = tf.transpose(tf.reshape(tf.transpose(eular_distance_raw), [doc_negative_num+1, batch_size]))
    return eular_distance

def softmax_loss(distance_sim,view=True):
    with tf.name_scope('softmax_loss'):
        # 转化为softmax概率矩阵。
        prob = tf.nn.softmax(distance_sim)
        # 只取第一列，即正样本列概率。
        hit_prob = tf.slice(prob, [0, 0], [-1, 1])
        loss = -tf.reduce_sum(tf.log(hit_prob))
        if view:
            tf.summary.scalar('softmax_loss', loss)
    return prob,loss

def triplet_loss(distance_sim,margin=1.0,view=True):
    with tf.name_scope('triplet_loss'):   
        d_pos = distance_sim[0,:]
        d_neg = distance_sim[1,:]

        loss = tf.maximum(0., margin + d_pos - d_neg)
        loss = tf.reduce_mean(loss)
        if view:
            tf.summary.scalar('triplet_loss', loss)
        return None,loss


def train_loss_layer(query_y,doc_positive_y,doc_negative_y,query_BS):
    """
    cos_sim : [2,query_BS]
    """
    if FLAGS_distance_type == 'cos':
        sim = cos_distance_layer(query_y,doc_positive_y,doc_negative_y,1,query_BS)
    else:
        sim = eular_distance_layer(query_y,doc_positive_y,doc_negative_y,1,query_BS)

    if FLAGS_loss_type == 'softmax':
        _,loss = softmax_loss(sim)
    else:
        _,loss =triplet_loss(sim)

   
    return sim,loss

def triple_loss_layer(query_y,doc_positive_y,doc_negative_y):
    """
    cos_sim : [2,1]
    """
    if FLAGS_distance_type == 'cos':
        sim = cos_distance_layer(query_y,doc_positive_y,doc_negative_y,1,1)
    else:
        sim = eular_distance_layer(query_y,doc_positive_y,doc_negative_y,1,1)

    if FLAGS_loss_type == 'softmax':
        _,loss = softmax_loss(sim,view=False)
    else:
        _,loss =triplet_loss(sim,view=False)
    return cos_sim,loss

def accuracy_layer(prob):
    correct_prediction = tf.equal(tf.argmax(prob, 1), 0)
    accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))
    tf.summary.scalar('accuracy', accuracy)
    return accuracy

def predict_layer(query_y,doc_positive_y,main_question_num):
    """
    cos_sim : [main_len,1]
    """
    if FLAGS_distance_type == 'cos':
        sim = cos_distance_layer(query_y,doc_positive_y,main_question_num,1,1)
        label = tf.argmax(sim,1)[0]
    else:
        sim = eular_distance_layer(query_y,doc_positive_y,main_question_num,1,1)
        label = tf.argmin(sim,1)[0]

    return label

def average_gradients(tower_grads):
    """Calculate the average gradient for each shared variable across all towers.
    Note that this function provides a synchronization point across all towers.
    Args:
    tower_grads: List of lists of (gradient, variable) tuples. The outer list
      is over individual gradients. The inner list is over the gradient
      calculation for each tower.
    Returns:
     List of pairs of (gradient, variable) where the gradient has been averaged
     across all towers.
    """
    average_grads = []
    for grad_and_vars in zip(*tower_grads):
        # Note that each grad_and_vars looks like the following:
        #   ((grad0_gpu0, var0_gpu0), ... , (grad0_gpuN, var0_gpuN))
        grads = []
        for g, _ in grad_and_vars:
            # Add 0 dimension to the gradients to represent the tower.
            expanded_g = tf.expand_dims(g, 0)

            # Append on a 'tower' dimension which we will average over below.
            grads.append(expanded_g)

        # Average over the 'tower' dimension.
        grad = tf.concat(axis=0, values=grads)
        grad = tf.reduce_mean(grad, 0)

        # Keep in mind that the Variables are redundant because they are shared
        # across towers. So .. we will just return the first tower's pointer to
        # the Variable.
        v = grad_and_vars[0][1]
        grad_and_var = (grad, v)
        average_grads.append(grad_and_var)
    return average_grads