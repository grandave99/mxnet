# pylint: skip-file
import numpy as np
import mxnet as mx
import random
from numpy.testing import assert_allclose
from mxnet.test_utils import *

def np_softmax(x):
    # fix for old numpy on Travis not supporting keepdims
    # x = x - np.max(x, axis=-1, keepdims=True)
    x = x - np.max(x, axis=-1).reshape(x.shape[:-1] + (1,))
    x = np.exp(x)
    # x /= np.sum(x, axis=-1, keepdims=True)
    x /= np.sum(x, axis=-1).reshape(x.shape[:-1] + (1,))
    return x


def check_elementwise_sum_with_shape(shape, n):
    # forward
    inputs = [mx.symbol.Variable('arg%d' % i) for i in range(n)]
    out = mx.symbol.ElementWiseSum(*inputs, name='esum')
    arr = [mx.nd.empty(shape) for i in range(n)]
    arr_grad = [mx.nd.empty(shape) for i in range(n)]
    for i in range(n):
        arr[i][:] = np.random.uniform(-10, 10, shape)
    exec1 = out.bind(default_context(),
                     args=arr,
                     args_grad=arr_grad)
    out1 = exec1.outputs[0].asnumpy()
    exec1.forward()
    out1 = exec1.outputs[0].asnumpy()
    out = sum(a.asnumpy() for a  in arr)

    assert reldiff(out, out1) < 1e-6
    out_grad = mx.nd.empty(shape)
    out_grad[:] = np.random.uniform(-10, 10, shape)
    # backward
    exec1.backward([out_grad])
    for a in arr_grad:
        assert same(a.asnumpy(), out_grad.asnumpy())

def test_elementwise_sum():
    np.random.seed(0)
    nrepeat = 2
    maxdim = 4
    for repeat in range(nrepeat):
        for dim in range(1, maxdim):
            shape = tuple(np.random.randint(1, int(1000**(1.0/dim)), size=dim))
            check_elementwise_sum_with_shape(shape, np.random.randint(1, 8))


def check_concat_with_shape(shapes, dimension, skip_second):
    # if skip_second is True, second argument will not have gradient.
    # it is to test #1130
    n = len(shapes)
    # forward
    target_dim = 0
    for shape in shapes:
        target_dim += shape[dimension]

    inputs = [mx.symbol.Variable('arg%d' % i) for i in range(n)]
    out = mx.symbol.Concat(*inputs, name='conc',dim=dimension)
    arr = [mx.nd.empty(shape) for shape in shapes]
    for i in range(n):
        arr[i][:] = shapes[i][dimension]
    arr_np = [np.copy(narray.asnumpy()) for narray in arr]
    arr_grad = [mx.nd.empty(shape) for shape in shapes]
    dict_grad = {}
    arg_names = out.list_arguments()

    for name, g in zip(arg_names, arr_grad):
        if not skip_second or name != 'arg1':
            dict_grad[name] = g

    args = out.list_arguments()
    arg_shapes, out_shapes, aux_shapes = out.infer_shape(**dict(zip(args, shapes)))
    out_grad = mx.nd.empty(out_shapes[0])
    exec1 = out.bind(default_context(),
                     args=arr,
                     args_grad=dict_grad)
    exec1.forward()
    out1 = exec1.outputs[0]
    ret = np.concatenate([narray.asnumpy() for narray in arr], axis=dimension)
    assert same(out1.asnumpy(), ret)
    # backward
    out1.copyto(out_grad)
    out_grad[:] += 1
    exec1.backward([out_grad])

    for i, name in enumerate(arg_names):
        if not skip_second or name != 'arg1':
            grad = dict_grad[name]
            np_grad = arr_np[i]
            assert same(grad.asnumpy(), np_grad + 1)

def test_concat():
    for dimension in range(4):
        n = 2
        merge = [2, 3, 4, 5, 6]
        a = 2
        b = 3
        c = 4
        # test  2D
        if dimension<2:
            for dim in range(2, 6):
                shapes = []
                for i in range(dim):
                    if dimension == 0:
                        shapes.append((merge[i], a))
                    elif dimension == 1:
                        shapes.append((a, merge[i]))
                    check_concat_with_shape(shapes,dimension,True)
                    check_concat_with_shape(shapes,dimension,False)
        #test 3D
        if dimension<3:
            for dim in range(2, 6):
                shapes = []
                for i in range(dim):
                    if dimension == 0:
                        shapes.append((merge[i], a,b))
                    elif dimension ==1:
                        shapes.append((a,merge[i],b))
                    elif dimension ==2:
                        shapes.append((a,b,merge[i]))
                check_concat_with_shape(shapes,dimension,True)
                check_concat_with_shape(shapes,dimension,False)
        # test 4D
        for dim in range(2, 6):
            shapes = []
            for i in range(dim):
                if dimension == 0:
                    shapes.append((merge[i],a,b,c))
                elif dimension == 1:
                    shapes.append((a,merge[i],b,c))
                elif dimension ==2:
                    shapes.append((a,b,merge[i],c))
                elif dimension ==3:
                    shapes.append((a,b,c,merge[i]))
            check_concat_with_shape(shapes,dimension,True)
            check_concat_with_shape(shapes,dimension,False)

def test_slice_channel():
    def check_slice_channel(data_ndim, axis, num_outputs, squeeze_axis):
        ins = []
        if squeeze_axis:
            shape = np.random.randint(2, 5, data_ndim).tolist()
            shape[axis] = num_outputs
            out_ele_shape = [ele for ele in shape]
            del out_ele_shape[axis]
        else:
            shape = np.random.randint(1, 5, data_ndim).tolist()
            shape[axis] *= num_outputs
            out_ele_shape = [ele for ele in shape]
            out_ele_shape[axis] //= num_outputs
        data_npy = np.random.normal(size=shape)
        out_grads_npy = [np.random.normal(size=out_ele_shape) for i in range(num_outputs)]
        data = mx.sym.Variable('data')
        sym = mx.sym.SliceChannel(data=data, num_outputs=num_outputs, axis=axis, squeeze_axis=squeeze_axis)
        exe = sym.simple_bind(ctx=default_context(), data=data_npy.shape)
        assert len(exe.outputs) == num_outputs
        outputs = exe.forward(is_train=True, data=data_npy)
        for i in range(num_outputs):
            gt = data_npy.take(np.arange(i * shape[axis]/num_outputs,
                                         (i+1) * shape[axis]/num_outputs).astype(np.int), axis=axis)
            if squeeze_axis:

                assert reldiff(outputs[i].asnumpy(), gt.reshape(outputs[i].shape)) < 1e-5
            else:
                assert reldiff(outputs[i].asnumpy(), gt) < 1e-5
        # test backward
        exe.backward(out_grads=[mx.nd.array(ele, ctx=default_context()) for ele in out_grads_npy])
        if squeeze_axis:
            assert reldiff(exe.grad_arrays[0].asnumpy(),
                           np.concatenate([np.expand_dims(ele, axis=axis) for ele in out_grads_npy],
                                          axis=axis)) < 1e-5
        else:
            assert reldiff(exe.grad_arrays[0].asnumpy(),
                           np.concatenate(out_grads_npy, axis=axis)) < 1e-5
    check_slice_channel(data_ndim=2, axis=1, num_outputs=3, squeeze_axis=True)
    check_slice_channel(data_ndim=4, axis=2, num_outputs=3, squeeze_axis=False)
    check_slice_channel(data_ndim=3, axis=-1, num_outputs=2, squeeze_axis=False)
    check_slice_channel(data_ndim=5, axis=-2, num_outputs=3, squeeze_axis=True)


def check_regression(symbol, forward, backward):
    data = mx.symbol.Variable('data')
    label = mx.symbol.Variable('label')
    out = symbol(data, label)
    shape = (3, 1)
    arr_data = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(default_context())
    arr_label = mx.random.uniform(0, 1, shape[0], ctx=mx.cpu()).copyto(default_context())
    arr_grad = mx.nd.empty(shape)
    exec1 = out.bind(default_context(),
                     args=[arr_data, arr_label],
                     args_grad={"data" : arr_grad})
    exec1.forward()
    out1 = exec1.outputs[0].asnumpy()
    npout = forward(arr_data.asnumpy())
    assert reldiff(npout, out1) < 1e-6

    exec1.backward()
    npout = backward(npout,  arr_label.asnumpy().reshape(npout.shape))
    assert reldiff(npout, arr_grad.asnumpy()) < 1e-6

def test_regression():
    check_regression(mx.symbol.LogisticRegressionOutput,
                     lambda x: 1.0 / (1.0 + np.exp(-x)),
                     lambda x, y : x - y)
    check_regression(mx.symbol.LinearRegressionOutput,
                     lambda x: x,
                     lambda x, y : x - y)

def check_softmax_with_ignore_label(xpu):
    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L')
    Y = mx.symbol.SoftmaxOutput(data=X, label=L, ignore_label=0, use_ignore=True)

    shape = (20, 10)
    x = mx.nd.empty(shape, ctx = xpu)
    l = mx.nd.empty((shape[0],), ctx = xpu)
    x_np = np.random.rand(*shape)
    l_np = np.random.randint(0, shape[1]-1, (shape[0],))
    x[:] = x_np
    l[:] = l_np

    grad = mx.nd.empty(shape, ctx = xpu)

    exec1 = Y.bind(xpu, args = [x, l], args_grad = {'X': grad})
    exec1.forward()
    exec1.backward()

    grad0 = grad.asnumpy()

    for i in range(int(shape[0]/2)):
        l_np[i] = 0
    l[:] = l_np

    exec1.forward()
    exec1.backward()
    grad1 = grad.asnumpy()

    assert(abs(np.sum(grad1[:int(shape[0]/2)])) < 1e-5)
    assert(reldiff(grad0[int(shape[0]/2):], grad1[int(shape[0]/2):]) < 1e-5)

def check_softmax_with_shape(shape, xpu, preserve_shape=False):
    # bind with label
    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L')
    Y = mx.symbol.SoftmaxOutput(data=X, label=L, preserve_shape=preserve_shape)
    x = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    l = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    l[:] = np_softmax(l.asnumpy())
    grad = mx.nd.empty(shape, ctx = xpu)
    exec1 = Y.bind(xpu, args = [x, l], args_grad = {'X': grad})
    exec1.forward()
    out = exec1.outputs[0].asnumpy()
    assert_allclose(out, np_softmax(x.asnumpy()), rtol=1e-4)
    exec1.backward()
    assert_allclose(grad.asnumpy(), np_softmax(x.asnumpy()) - l.asnumpy(), rtol=1e-4)

def test_softmax():
    check_softmax_with_shape((3, 4), default_context(), preserve_shape=False)
    check_softmax_with_shape((3, 4), default_context(), preserve_shape=True)
    check_softmax_with_shape((3, 4, 2), default_context(), preserve_shape=True)

def check_multi_softmax_with_shape(shape, xpu):
    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L')
    Y = mx.symbol.SoftmaxOutput(data=X, label=L, multi_output=True)
    x = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    l = mx.nd.empty((shape[0], shape[2]), ctx = xpu)
    l[:] = np.random.randint(0, shape[1]-1, (shape[0], shape[2]))
    grad = mx.nd.empty(shape, ctx = xpu)

    exec1 = Y.bind(xpu, args = [x, l], args_grad = {'X': grad})
    exec1.forward()
    print(exec1.outputs[0].asnumpy())
    exec1.backward()
    print(grad.asnumpy())

def test_python_op():
    X = mx.symbol.Variable('X')
    op = mx.operator.NumpyOp()
    s = op.get_symbol(X, name='numpy_op')

    x = mx.ndarray.ones((10))*10
    dx = mx.ndarray.zeros((10))
    dy = mx.ndarray.ones((10))
    exec1 = s.bind(default_context(), args=[x], args_grad = {'X': dx})
    exec1.forward()
    assert reldiff(x.asnumpy(), exec1.outputs[0].asnumpy()) < 1e-5
    exec1.backward(dy)
    assert reldiff(dy.asnumpy(), dx.asnumpy()) < 1e-5

def test_swapaxes():
    data = mx.symbol.Variable('data')
    shape = (2, 3, 4)
    data_tmp = np.ones(shape)
    data_tmp[0] = 1
    data_tmp[1] = 2
    arr_data = mx.nd.array(data_tmp)
    swap0 = mx.symbol.SwapAxis(data=data, dim1=0, dim2=2)
    swap = mx.symbol.SwapAxis(data=swap0, dim1=1, dim2=2)
    exe_c = swap.bind(default_context(), args=[arr_data])
    exe_c.forward()
    out = exe_c.outputs[0].asnumpy()

    swap0_ = np.swapaxes(data_tmp, 0, 2)
    swap_ = np.swapaxes(swap0_, 1, 2)

    assert reldiff(out, swap_) < 1e-6

def test_scalarop():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)*5
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:]=3

    test = 2 / (4-((1+data+1)*2/5)-0.2)

    npout_1 = (4-((1+data_tmp+1)*2/5)-0.2)
    npout = 2/npout_1

    check_symbolic_forward(test, [data_tmp], [npout])

    npout_grad = 2.*2/5
    npout_grad = 2*npout_grad /(npout_1 *npout_1 )

    check_symbolic_backward(test, [data_tmp], [np.ones(shape)*2], [npout_grad])


def test_scalar_pow():
    data = mx.symbol.Variable('data')
    shape = (1, 1)
    data_tmp = np.ones(shape)
    test = data ** 2
    check_numeric_gradient(test, [data_tmp])
    check_symbolic_forward(test, [data_tmp], [data_tmp ** 2])
    check_symbolic_backward(test, [data_tmp], [np.ones(shape)], [2 * data_tmp])

def test_symbol_pow():
    shape = (1, 1)

    data = mx.symbol.Variable('data')
    data_tmp = np.ones(shape)*2

    exp = mx.symbol.Variable('exp')
    exp_tmp = np.ones(shape)*3

    test = data**exp

    check_numeric_gradient(test, [data_tmp, exp_tmp])
    check_symbolic_forward(test, [data_tmp, exp_tmp], [data_tmp**exp_tmp])

    data_dir = data_tmp**(exp_tmp - 1) * exp_tmp
    exp_dir = data_tmp**(exp_tmp) * np.log(data_tmp)
    check_symbolic_backward(test, [data_tmp, exp_tmp], [np.ones(shape)], [data_dir, exp_dir])

def test_pow_fn():
    shape = (3, 4)
    exp = mx.symbol.Variable("exp")
    y = mx.sym.pow(2, exp)
    x = np.ones(shape)*3
    check_numeric_gradient(y, [x])
    check_symbolic_forward(y, [x], [2**x])
    check_symbolic_backward(y, [x], [np.ones(shape)], [np.log(2) * 2**x])

def test_binary_logic():
    def _inner_test(forward_gt, logic_sym, x_shape, y_shape, test_scalar=True):
        x = mx.symbol.Variable("x")
        y = mx.symbol.Variable("y")
        z = logic_sym(x, y)
        x_npy = np.random.randint(0, 4, size=x_shape).astype(np.float32)
        y_npy = np.random.randint(0, 4, size=y_shape).astype(np.float32)
        exe = z.simple_bind(ctx=default_context(), x=x_shape, y=y_shape)
        mx_out = exe.forward(is_train=True, x=x_npy, y=y_npy)[0].asnumpy()
        assert_allclose(mx_out, forward_gt(x_npy, y_npy))
        exe.backward()
        if test_scalar:
            z_lscalar = logic_sym(1, y)
            z_rscalar = logic_sym(x, 1)
            exe_lscalar = z_lscalar.simple_bind(ctx=default_context(), y=y_shape)
            exe_rscalar = z_rscalar.simple_bind(ctx=default_context(), x=x_shape)
            mx_lscalar_out = exe_lscalar.forward(is_train=True, y=y_npy)[0].asnumpy()
            mx_rscalar_out = exe_rscalar.forward(is_train=True, x=x_npy)[0].asnumpy()
            assert_allclose(mx_lscalar_out, forward_gt(1, y_npy))
            assert_allclose(mx_rscalar_out, forward_gt(x_npy, 1))
            exe_lscalar.backward()
            exe_rscalar.backward()
    # Test the no-broadcasting binary logic ops + scalar logic ops
    _inner_test(forward_gt=lambda x, y: x == y,
                logic_sym=lambda x, y: x == y, x_shape=(10, 10), y_shape=(10, 10))
    _inner_test(forward_gt=lambda x, y: x > y,
                logic_sym=lambda x, y: x > y, x_shape=(10, 10), y_shape=(10, 10))
    _inner_test(forward_gt=lambda x, y: x >= y,
                logic_sym=lambda x, y: x >= y, x_shape=(10, 10), y_shape=(10, 10))
    _inner_test(forward_gt=lambda x, y: x < y,
                logic_sym=lambda x, y: x < y, x_shape=(10, 10), y_shape=(10, 10))
    _inner_test(forward_gt=lambda x, y: x <= y,
                logic_sym=lambda x, y: x <= y, x_shape=(10, 10), y_shape=(10, 10))
    _inner_test(forward_gt=lambda x, y: x != y,
                logic_sym=lambda x, y: x != y, x_shape=(10, 10), y_shape=(10, 10))
    # Test the broadcasting binary logic ops
    _inner_test(forward_gt=lambda x, y: x == y,
                logic_sym=lambda x, y: mx.sym.broadcast_equal(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)
    _inner_test(forward_gt=lambda x, y: x > y,
                logic_sym=lambda x, y: mx.sym.broadcast_greater(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)
    _inner_test(forward_gt=lambda x, y: x >= y,
                logic_sym=lambda x, y: mx.sym.broadcast_greater_equal(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)
    _inner_test(forward_gt=lambda x, y: x < y,
                logic_sym=lambda x, y: mx.sym.broadcast_lesser(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)
    _inner_test(forward_gt=lambda x, y: x <= y,
                logic_sym=lambda x, y: mx.sym.broadcast_lesser_equal(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)
    _inner_test(forward_gt=lambda x, y: x != y,
                logic_sym=lambda x, y: mx.sym.broadcast_not_equal(x, y),
                x_shape=(1, 10), y_shape=(10, 1), test_scalar=False)

def test_embedding():
    in_dim = 10
    out_dim = 4
    batch = 24

    data = mx.sym.Variable("data")
    embed = mx.sym.Embedding(data=data, input_dim=in_dim, output_dim=out_dim, name="embed")
    exe_test = embed.simple_bind(default_context(), grad_req={'data': 'null', 'embed_weight': 'write'}, data=(batch,))
    arg_map = dict(zip(embed.list_arguments(), exe_test.arg_arrays))
    grad_map = dict(zip(embed.list_arguments(), exe_test.grad_arrays))
    np_data = np.random.randint(low=0, high=in_dim, size=batch)
    np_weight = np.random.uniform(-0.01, 0.01, arg_map["embed_weight"].shape)
    np_onehot = np.zeros((batch, in_dim))
    np_onehot[np.arange(batch), np_data] = 1.0
    # forward
    arg_map["data"][:] = np_data
    arg_map["embed_weight"][:] = np_weight
    exe_test.forward()
    assert reldiff(exe_test.outputs[0].asnumpy(), np.dot(np_onehot, np_weight)) < 1e-6
    # backward
    np_grad = np.random.uniform(-1, 1, exe_test.outputs[0].shape)
    grad = mx.nd.zeros(np_grad.shape)
    grad[:] = np_grad
    exe_test.backward([grad])
    assert reldiff(grad_map["embed_weight"].asnumpy(), np.dot(np_onehot.T, np_grad)) < 1e-6

# check ops handle duplicate input correctly.
def test_binary_op_duplicate_input():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:] = 5
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:] = 3
    out_grad = mx.nd.empty(shape)
    out_grad[:] = 1
    square = data * data
    exe_square = square.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_square.forward()
    assert reldiff(exe_square.outputs[0].asnumpy(), data_tmp * data_tmp) < 1e-6
    exe_square.backward(out_grad)
    assert reldiff(arr_grad.asnumpy(), 2.0 * data_tmp) < 1e-6

def test_sign():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:]=5
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:]=3

    test = mx.sym.sign(data)
    exe_test = test.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = np.sign(data_tmp)
    assert reldiff(out, npout) < 1e-6

    out_grad = mx.nd.empty(shape)
    out_grad[:] = 2;
    npout_grad = out_grad.asnumpy()
    npout_grad = 0;
    exe_test.backward(out_grad)
    assert reldiff(arr_grad.asnumpy(), npout_grad) < 1e-6

def test_round_ceil_floor():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:]=5.543
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:]= 2

    test = mx.sym.round(data) + mx.sym.ceil(data) +  mx.sym.floor(data)
    exe_test = test.bind(default_context(), args=[arr_data])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = np.round(data_tmp) + np.ceil(data_tmp) + np.floor(data_tmp)
    assert reldiff(out, npout) < 1e-6

def test_rsqrt_cos_sin():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:]=5
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:]=3

    test =  mx.sym.rsqrt(data) + mx.sym.cos(data) + mx.sym.sin(data)
    exe_test = test.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout =  1/ np.sqrt(data_tmp) + np.cos(data_tmp) + np.sin(data_tmp)
    assert reldiff(out, npout) < 1e-6

    out_grad = mx.nd.empty(shape)
    out_grad[:] = 2;
    npout_grad = out_grad.asnumpy()
    npout_grad = npout_grad * -(1.0 / (2.0 * data_tmp * np.sqrt(data_tmp))) + npout_grad * -1 * np.sin(data_tmp) + npout_grad * np.cos(data_tmp)
    exe_test.backward(out_grad)
    assert reldiff(arr_grad.asnumpy(), npout_grad) < 1e-6

def test_maximum_minimum():
    data1 = mx.symbol.Variable('data')
    data2 = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp1 = np.random.rand(3,4)
    data_tmp2 = np.random.rand(3,4)
    data_tmp1[:] = 2
    data_tmp2[:] = 3

    arr_data1 = mx.nd.array(data_tmp1)
    arr_data2 = mx.nd.array(data_tmp2)


    arr_grad1 = mx.nd.empty(shape)
    arr_grad2 = mx.nd.empty(shape)


    test =  mx.sym.maximum(data1,data2) + mx.sym.minimum(data1,data2);
    exe_test = test.bind(default_context(), args=[arr_data1,arr_data2], args_grad=[arr_grad1,arr_grad2])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout =  np.maximum(data_tmp1,data_tmp2) + np.minimum(data_tmp1,data_tmp2)
    assert reldiff(out, npout) < 1e-6

    out_grad = mx.nd.empty(shape)
    out_grad[:] = 2
    exe_test.backward(out_grad)

    npout_grad = np.ones(shape)
    npout_grad[:] = 2
    mask1 = (data_tmp1 > data_tmp2).astype('float')
    mask2 = (data_tmp1 < data_tmp2).astype('float')
    npout_grad1 = npout_grad * mask1 + npout_grad * mask2
    npout_grad2 = (npout_grad - npout_grad * mask1) + (npout_grad - npout_grad * mask2)

    assert reldiff(arr_grad1.asnumpy(), npout_grad1) < 1e-6
    assert reldiff(arr_grad2.asnumpy(), npout_grad2) < 1e-6

def test_maximum_minimum_scalar():
    data1 = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp1 = np.random.rand(3,4)
    data_tmp1[:] = 2

    arr_data1 = mx.nd.array(data_tmp1)
    arr_grad1 = mx.nd.empty(shape)

    test =  mx.sym.maximum(data1,3) + mx.sym.maximum(9,data1) + mx.sym.minimum(5,data1) + mx.sym.minimum(data1,4)
    exe_test = test.bind(default_context(), args=[arr_data1], args_grad=[arr_grad1])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout =  np.maximum(data_tmp1,3) + np.maximum(9,data_tmp1) + np.minimum(5,data_tmp1) + np.minimum(data_tmp1,4)
    assert reldiff(out, npout) < 1e-6

    out_grad = mx.nd.empty(shape)
    out_grad[:] = 2
    exe_test.backward(out_grad)

    npout_grad = np.ones(shape)
    npout_grad[:] = 2
    mask1 = (data_tmp1 > 3).astype('float')
    mask2 = (9 > data_tmp1).astype('float')
    mask3 = (5 < data_tmp1).astype('float')
    mask4 = (data_tmp1 < 4).astype('float')
    npout_grad1 = npout_grad * mask1 + (npout_grad - npout_grad * mask2) + (npout_grad - npout_grad * mask3) + npout_grad * mask4

    assert reldiff(arr_grad1.asnumpy(), npout_grad1) < 1e-6

def test_abs():
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:]=5
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:]=3

    test = mx.sym.abs(data)
    exe_test = test.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = abs(data_tmp)
    assert reldiff(out, npout) < 1e-6

    out_grad = mx.nd.empty(shape)
    out_grad[:] = 2;
    npout_grad = out_grad.asnumpy()
    npout_grad = npout_grad * np.sign(data_tmp)
    exe_test.backward(out_grad)
    assert reldiff(arr_grad.asnumpy(), npout_grad) < 1e-6

def check_deconvolution_forward_backward(input_shape, num_filter, kernel, stride, pad):
    """configure A: input --> conv --> deconv --> output.
       the convolution and deconvoluiton has similar parameter which ensure
       the input shape is the same as output, and the same weights between conv
       and deconv;
       If the input value of forward() and backwrad() is the same, then
       the output value of them should also the same;
    """
    assert input_shape[1] == num_filter
    data = mx.sym.Variable(name="data")
    conv = mx.sym.Convolution(
        data=data, kernel=kernel, stride=stride, pad=pad,
        num_filter=num_filter, no_bias = "true", name = "conv")
    deconv = mx.sym.Deconvolution(
        data=conv, kernel=kernel, stride=stride, pad=pad,
        num_filter=num_filter, no_bias = "true", name = "deconv")

    arg_names = deconv.list_arguments()
    arg_shapes, out_shapes, _ = deconv.infer_shape(data=input_shape)
    input_data = mx.random.uniform(-5, 5, input_shape, ctx=mx.cpu()).copyto(default_context())
    out_grad = input_data
    args = {}
    args["data"] = input_data
    args['conv_weight'] = args['deconv_weight'] = mx.random.normal(0, 1,
        (num_filter, input_shape[1]) + kernel, ctx=mx.cpu()).copyto(default_context())
    args_grad = [mx.nd.empty(s) for s in arg_shapes]

    exe = deconv.bind(default_context(), args=args, args_grad=args_grad)
    exe.forward()
    out = exe.outputs[0].asnumpy()
    exe.backward(out_grad)
    assert reldiff(out, args_grad[0].asnumpy()) < 1e-6

def check_deconvolution_gradient(input_shape, num_filter, pad):
    """configure A: input --> conv --> output.
       configure B: input --> deconv --> output
       the convolution and deconvoluiton has similar parameter which ensure
       the input shape is the same as output;
       During backward(), if the input of A equals output of B, and the output
       of A equals input of B, then the grad of weight should be the same;
    """
    stride = (1, 1)
    kernel = (2*pad[0]+1, 2*pad[1]+1)
    data_conv = mx.sym.Variable(name="data_conv")
    conv = mx.sym.Convolution(
        data=data_conv, kernel=kernel, stride=stride, pad=pad,
        num_filter=num_filter, no_bias = "true", name = "conv")
    data_deconv = mx.sym.Variable(name="data_deconv")
    deconv = mx.sym.Deconvolution(
        data=data_deconv, kernel=kernel, stride=stride, pad=pad,
        num_filter=num_filter, no_bias = "true", name = "deconv")

    conv_data = mx.random.uniform(-5, 5, input_shape, ctx=mx.cpu()).copyto(default_context())
    conv_args = {}
    conv_args["data_conv"] = conv_data
    conv_args['conv_weight'] = \
        mx.random.normal(0, 1,(num_filter, input_shape[1]) + kernel, ctx=mx.cpu()).copyto(default_context())
    conv_args_grad = [mx.nd.zeros(conv_data.shape),
        mx.nd.zeros((num_filter, input_shape[1]) + kernel)]
    exe_conv = conv.bind(default_context(), args=conv_args, args_grad=conv_args_grad)
    exe_conv.forward(is_train=True)
    conv_out_grad = mx.random.normal(0, 2, exe_conv.outputs[0].shape, ctx=mx.cpu()).copyto(default_context())
    exe_conv.backward(conv_out_grad)

    deconv_data = conv_out_grad
    deconv_args = {}
    deconv_args['data_deconv'] = deconv_data
    deconv_args['deconv_weight'] = conv_args['conv_weight']
    deconv_args_grad = [mx.nd.zeros(deconv_data.shape),
        mx.nd.zeros((num_filter, input_shape[1]) + kernel)]
    exe_deconv = deconv.bind(default_context(), args=deconv_args, args_grad=deconv_args_grad)
    exe_deconv.forward(is_train=True)
    deconv_out_grad = conv_data[:]
    exe_deconv.backward(deconv_out_grad)
    assert reldiff(conv_args_grad[1].asnumpy(), deconv_args_grad[1].asnumpy()) < 1e-6

def check_deconvolution_target_shape(input_shape, kernel, stride, pad, adj, target_shape=None):
    data = mx.sym.Variable(name="data")
    deconv = mx.sym.Deconvolution(
        data=data, kernel=kernel, stride=stride, pad=pad, adj=adj, num_filter=5,
        target_shape = target_shape if target_shape is not None else (0, 0))
    arg_names = deconv.list_arguments()
    arg_shapes, out_shapes, _ = deconv.infer_shape(data=input_shape)
    assert out_shapes[0] == (input_shape[0], 5, 8, 8)

def test_deconvolution():
    check_deconvolution_target_shape(
        input_shape         = (2,3,4,4),
        kernel              = (3,3),
        stride              = (2,2),
        target_shape        = (8,8),
        pad                 = (99,99),  # will be ignored
        adj                 = (101,101),  # will be ignored
    )
    check_deconvolution_target_shape(
        input_shape         = (2,3,4,4),
        kernel              = (3,3),
        stride              = (2,2),
        pad                 = (1,1),
        adj                 = (1,1),
    )
    check_deconvolution_forward_backward(
        input_shape         = (1,1,5,5),
        num_filter          = 1,
        kernel              = (3,3),
        stride              = (1,1),
        pad                 = (1,1)
    )
    check_deconvolution_forward_backward(
        input_shape         = (32,3,28,28),
        num_filter          = 3,
        kernel              = (3,3),
        stride              = (1,1),
        pad                 = (1,1)
    )
    check_deconvolution_forward_backward(
        input_shape         = (10, 3, 403, 403),
        num_filter          = 3,
        kernel              = (7,7),
        stride              = (5,5),
        pad                 = (2,2)
    )
    check_deconvolution_gradient(
        input_shape = (1,3,5,5),
        num_filter = 3,
        pad = (1,1)
    )
    check_deconvolution_gradient(
        input_shape = (5,3,100,100),
        num_filter = 3,
        pad = (3,3)
    )

def check_nearest_upsampling_with_shape(shapes, scale, root_scale):
    arr = {'arg_%d'%i: mx.random.uniform(-10.0, 10.0, shape, ctx=mx.cpu()).copyto(default_context()) for i, shape in zip(range(len(shapes)), shapes)}
    arr_grad = {'arg_%d'%i: mx.nd.zeros(shape) for i, shape in zip(range(len(shapes)), shapes)}

    up = mx.sym.UpSampling(*[mx.sym.Variable('arg_%d'%i) for i in range(len(shapes))], sample_type='nearest', scale=root_scale)
    exe = up.bind(default_context(), args=arr, args_grad=arr_grad)
    exe.forward(is_train=True)
    exe.backward(exe.outputs)
    for k in range(len(shapes)):
        name = 'arg_%d'%k
        assert_allclose(arr[name].asnumpy()*root_scale**2*scale**(2*k), arr_grad[name].asnumpy(), rtol=1e-4)


def test_nearest_upsampling():
    for root_scale in [1,2,3]:
        for scale in [1,2,3]:
            for num_shape in [1,2,3]:
                for base in [1,2,3]:
                    shapes = [(1,3,base*root_scale*scale**(num_shape-1-i),base*root_scale*scale**(num_shape-1-i)) for i in range(num_shape)]
                    check_nearest_upsampling_with_shape(shapes, scale, root_scale)

def test_batchnorm_training():
    for shape in [(2, 3), (2, 3, 2, 2)]:
        data_tmp = np.random.normal(size=shape)
        s = shape[1],
        gamma = np.ones(s)
        beta = np.ones(s)
        gamma[1] = 3
        beta[0] = 3

        rolling_mean = np.random.uniform(size=s)
        rolling_std = np.random.uniform(size=s)

        data = mx.symbol.Variable('data')
        test = mx.symbol.BatchNorm(data, fix_gamma=False)
        check_numeric_gradient(test, [data_tmp, gamma, beta], [rolling_mean, rolling_std], numeric_eps=1e-2, check_eps=0.16)

        test = mx.symbol.BatchNorm(data, fix_gamma=False, use_global_stats=True)
        check_numeric_gradient(test, [data_tmp, gamma, beta], [rolling_mean, rolling_std], numeric_eps=1e-2, check_eps=0.16)

def test_convolution_grouping():
    num_filter = 4
    num_group = 2
    kernel = (3, 3)
    shape = (1, 4, 9, 9)

    x = mx.sym.Variable('x')
    w = mx.sym.Variable('w')
    b = mx.sym.Variable('b')
    y1 = mx.sym.Convolution(data=x, weight=w, bias=b, num_filter=num_filter, num_group=num_group, kernel=kernel)
    xslice = mx.sym.SliceChannel(data=x, num_outputs=num_group, axis=1)
    wslice = mx.sym.SliceChannel(data=w, num_outputs=num_group, axis=0)
    bslice = mx.sym.SliceChannel(data=b, num_outputs=num_group, axis=0)
    y2 = mx.sym.Concat(*[mx.sym.Convolution(data=xslice[i], weight=wslice[i], bias=bslice[i],
                                            num_filter=num_filter//num_group, kernel=kernel)
                       for i in range(num_group)])

    exe1 = y1.simple_bind(default_context(), x=shape)
    exe2 = y2.simple_bind(default_context(), x=shape, w=(num_filter, shape[1]//num_group, kernel[0], kernel[1]), b=(num_filter,))
    for arr1, arr2 in zip(exe1.arg_arrays, exe2.arg_arrays):
        arr1[:] = np.random.normal(size=arr1.shape)
        arr2[:] = arr1
    exe1.forward(is_train=True)
    exe1.backward(exe1.outputs[0])
    exe2.forward(is_train=True)
    exe2.backward(exe2.outputs[0])

    for arr1, arr2 in zip(exe1.outputs + exe1.grad_arrays, exe2.outputs + exe2.grad_arrays):
        np.testing.assert_allclose(arr1.asnumpy(), arr2.asnumpy(), rtol=1e-3)

def gen_broadcast_data():
    # Generate random data that has ndim between 1-7 and all the shape dims between 1-5
    ndim = np.random.randint(1, 6)
    shape = np.random.randint(1, 6, size=(ndim,))
    l_same_dim = np.random.randint(0, 5)
    r_same_dim = np.random.randint(0, 5)
    l_axis_flags = np.random.randint(0, 2, size=ndim)
    r_axis_flags = np.random.randint(0, 2, size=ndim)
    if l_same_dim == 4:
        l_axis_flags = np.ones(ndim)
    if r_same_dim == 4:
        r_axis_flags = np.ones(ndim)
    l_shape = shape.copy()
    r_shape = shape.copy()
    l_shape[np.where(l_axis_flags == 0)] = 1
    r_shape[np.where(r_axis_flags == 0)] = 1
    return [np.random.random(l_shape), np.random.random(r_shape)]

def gen_binary_data():
    ndim = np.random.randint(1, 6)
    shape = np.random.randint(1, 6, size=(ndim,))
    return [np.random.random(shape), np.random.random(shape)]

def check_binary_op_forward(symbol, baseline, gen_data):
    sample_num = 200
    for i in range(sample_num):
        d = gen_data()
        x = baseline(d[0], d[1])
        y = symbol.bind(default_context(), args={'a': mx.nd.array(d[0]), 'b' : mx.nd.array(d[1])})
        y.forward()
        assert_allclose(x, y.outputs[0].asnumpy(), rtol=1e-3, atol=1e-5)

def check_binary_op_backward(symbol, baseline, gen_data):
    sample_num = 200
    for i in range(sample_num):
        d = gen_data()
        out = np.random.random((d[0] + d[1]).shape)
        def reduce_op(shape, x):
            if shape == x.shape:
                return x
            keepdims_shape = list(x.shape)
            for i in range(len(shape)):
                if x.shape[i] != shape[i]:
                    keepdims_shape[i] = 1
                    x = np.sum(x, axis=i).reshape(keepdims_shape)
            return x
        baseline_grad1, baseline_grad2 = baseline(out, d[0], d[1])
        x_1 = reduce_op(d[0].shape, baseline_grad1)
        x_2 = reduce_op(d[1].shape, baseline_grad2)
        y_1 = mx.nd.empty(d[0].shape)
        y_2 = mx.nd.empty(d[1].shape)
        y = symbol.bind(default_context(), args={'a': mx.nd.array(d[0]), 'b' : mx.nd.array(d[1])},
                        args_grad=[y_1, y_2])
        y.forward()
        y.backward([mx.nd.array(out)])
        assert_allclose(x_1, y_1.asnumpy(), rtol=1e-3, atol=1e-5)
        assert_allclose(x_2, y_2.asnumpy(), rtol=1e-3, atol=1e-5)

def test_binary_op():
    a = mx.sym.Variable('a')
    b = mx.sym.Variable('b')

    def test_bplus(a, b):
        c = a + b
        check_binary_op_forward(c, lambda a, b: a + b, gen_binary_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out, g_out), gen_binary_data)

    def test_bminus(a, b):
        c = a - b
        check_binary_op_forward(c, lambda a, b: a - b, gen_binary_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out, - g_out), gen_binary_data)

    def test_bmul(a, b):
        c = a * b
        check_binary_op_forward(c, lambda a, b: a * b, gen_binary_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out * b, g_out * a), gen_binary_data)

    def test_bdiv(a, b):
        c = a / b
        check_binary_op_forward(c, lambda a, b: a / b, gen_binary_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out / b, - g_out * a / (b * b)), gen_binary_data)

    def test_bpow(a, b):
        c = a ** b
        check_binary_op_forward(c, lambda a, b: a ** b, gen_binary_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out * a **(b - 1) * b,
                                        g_out * a ** b * np.log(a)), gen_binary_data)

    test_bplus(a, b)
    test_bminus(a, b)
    test_bmul(a, b)
    test_bdiv(a, b)
    test_bpow(a, b)

def test_broadcast_binary_op():
    a = mx.sym.Variable('a')
    b = mx.sym.Variable('b')

    def test_bplus(a, b):
        c = mx.sym.broadcast_plus(a, b)
        check_binary_op_forward(c, lambda a, b: a + b, gen_broadcast_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out, g_out), gen_broadcast_data)

    def test_bminus(a, b):
        c = mx.sym.broadcast_minus(a, b)
        check_binary_op_forward(c, lambda a, b: a - b, gen_broadcast_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out, - g_out), gen_broadcast_data)

    def test_bmul(a, b):
        c = mx.sym.broadcast_mul(a, b)
        check_binary_op_forward(c, lambda a, b: a * b, gen_broadcast_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out * b, g_out * a), gen_broadcast_data)

    def test_bdiv(a, b):
        c = mx.sym.broadcast_div(a, b)
        check_binary_op_forward(c, lambda a, b: a / b, gen_broadcast_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out / b, - g_out * a / (b * b)), gen_broadcast_data)

    def test_bpow(a, b):
        c = mx.sym.broadcast_power(a, b)
        check_binary_op_forward(c, lambda a, b: a ** b, gen_broadcast_data)
        check_binary_op_backward(c, lambda g_out, a, b: (g_out * a **(b - 1) * b,
                                        g_out * a ** b * np.log(a)), gen_broadcast_data)

    test_bplus(a, b)
    test_bminus(a, b)
    test_bmul(a, b)
    test_bdiv(a, b)
    test_bpow(a, b)

def test_run_convolution_dilated_impulse_response(dil=(1,1), kernel_shape=(3,3), verbose=False):
    # Input for spike response
    spike_imgs = np.zeros(shape=(1,1,33,33), dtype=np.float32)
    spike_imgs[0,0,16,16] = 1.0
    spike_img = mx.nd.array(spike_imgs)
    spike_img2 = mx.nd.array(spike_imgs)


    kernel_weights = mx.nd.ones(shape=tuple([1,1]+list(kernel_shape)), dtype=np.float32)
    kernel_weights2 = mx.nd.ones(shape=tuple([1,1]+list(kernel_shape)), dtype=np.float32)

    kernel = mx.symbol.Variable('kernel')
    in_img = mx.symbol.Variable('input')
    net = mx.symbol.Convolution(in_img, num_filter=1,kernel=kernel_shape, dilate=dil, no_bias="true", name='test_convolution')
    net.list_arguments()
    be = net.bind(default_context(), args={ 'input' : spike_img, 'test_convolution_weight' : kernel_weights},
                args_grad={'input' : spike_img2, 'test_convolution_weight' : kernel_weights2 } )
    be.forward(True)
    out_o = be.outputs[0].asnumpy()
    ndo = be.outputs[0]

    out_grads = np.zeros(shape=be.outputs[0].shape, dtype=np.float32)
    out_grads[0,0, 16,16] = 1.0
    out_grad = mx.nd.array(out_grads)
    be.backward([out_grad])
    vgrad = be.grad_arrays[0].asnumpy()
    out = out_o.reshape((out_o.shape[2],out_o.shape[3]))
    nzx,nzy = np.nonzero(out)
    assert(np.sum(out)==np.prod(kernel_shape))
    assert(np.sum(vgrad)==np.prod(kernel_shape))

    # Now check whether the input gradient was computed correctly
    input_grad = mx.nd.array(vgrad)

    be = net.bind(default_context(), args={ 'input' : input_grad, 'test_convolution_weight' : kernel_weights})
    be.forward(True)
    out_o = be.outputs[0].asnumpy()
    assert(out_o[0,0,16,16]==np.prod(kernel_shape))

    rnd_kernel_s = np.random.uniform(low=0.0, high=1.0, size=tuple([1,1]+list(kernel_shape))).astype(np.float32)
    impulse_error = mx.nd.array(out_o/np.sum(out_o)) # This should be 1.0 at [0,0,16,16]
    rnd_kernel = mx.nd.array(rnd_kernel_s)

    rnd_kernel2 = mx.nd.array(rnd_kernel_s)
    white_in = mx.nd.ones(shape=(1,1,33,33))
    white_in2 = mx.nd.ones(shape=(1,1,33,33))

    be = net.bind(default_context(), args={ 'input' : white_in, 'test_convolution_weight' : rnd_kernel},
                args_grad={'input' : white_in2, 'test_convolution_weight' : rnd_kernel2 } )

    be.forward(True)
    be.backward([impulse_error])
    out_orig = be.outputs[0].asnumpy()
    kernel_gradient = be.grad_arrays[1].asnumpy()

    dkernel = mx.nd.array(rnd_kernel_s + kernel_gradient)

    be = net.bind(default_context(), args={ 'input' : white_in, 'test_convolution_weight' : dkernel})

    be.forward(True)
    out = be.outputs[0].asnumpy()
    # Now do a simple check of the kernel gradient
    assert(out[0,0,16,16] - np.sum(kernel_gradient) - out_orig[0,0,16,16] < 0.001)


def test_convolution_dilated_impulse_response():
    for dil in [ (1,1), (2,2), (3,3) ]:
        for ks in [ (3,3), (4,4), (2,3), (3,2), (1,1) ]:
            test_run_convolution_dilated_impulse_response(dil=dil, kernel_shape=ks)

def test_reshape():

    def test_reshape_new(src_shape, shape_args, reverse, dst_shape):
        net = mx.sym.Variable("data")
        net = mx.sym.Reshape(net, shape=shape_args, reverse=reverse)
        js = net.tojson()
        net = mx.sym.load_json(js)
        _, output_shape, __ = net.infer_shape(data=src_shape)
        assert output_shape[0] == dst_shape, \
            'Src Shape = %s, Shape Arguments = %s, Reverse = %s, Dst Shape = %s, ' \
            'Output Shape = %s' %(str(src_shape), str(shape_args), str(reverse),
                                  str(dst_shape), str(output_shape[0]))
        dat_npy = np.random.rand(*src_shape)
        grad_npy = np.random.rand(*dst_shape)
        exe = net.simple_bind(default_context(), data=src_shape)
        exe.arg_dict['data'][:] = dat_npy
        exe.forward(is_train=True)
        assert np.square(exe.outputs[0].asnumpy() - dat_npy.reshape(dst_shape)).mean() < 1E-7, \
            'Src Shape = %s, Shape Arguments = %s, Reverse = %s, Dst Shape = %s'\
            %(str(src_shape), str(shape_args), str(reverse), str(dst_shape))
        exe.backward(out_grads=mx.nd.array(grad_npy))
        assert np.square(exe.grad_dict['data'].asnumpy() - grad_npy.reshape(src_shape)).mean() < 1E-7, \
            'Src Shape = %s, Shape Arguments = %s, Reverse = %s, Dst Shape = %s'\
            %(str(src_shape), str(shape_args), str(reverse), str(dst_shape))
    # Test new api (Using shape)
    test_cases = [
        [(2, 3, 5, 5),  (0, -1),          False, (2, 75)],
        [(2, 3, 5, 5),  (0, 0, -1),       False, (2, 3, 25)],
        [(5, 3, 4, 5),  (0, -1, 0),       False, (5, 15, 4)],
        [(2, 3, 5, 4),  (-1, 0, 0),       False, (8, 3, 5)],
        [(2, 3, 5, 5),  (0, 0, 0, 0),     False, (2, 3, 5, 5)],
        [(2, 4, 5, 3),  (-1, 2, 2, 1),    False, (30, 2, 2, 1)],
        [(2, 3, 5, 6),  (-2,),            False, (2, 3, 5, 6)],
        [(2, 3, 5, 6),  (6, 1, -2),       False, (6, 1, 5, 6)],
        [(2, 3, 5, 6),  (-3, -3),         False, (6, 30)],
        [(2, 3, 5, 6),  (-3, -1),         False, (6, 30)],
        [(64,),         (-4, 16, 4),      False, (16, 4)],
        [(64,),         (-4, 16, -1),     False, (16, 4)],
        [(64, 1, 2, 3), (-4, 16, -1, -2), False, (16, 4, 1, 2, 3)],
        [(2, 3, 5, 5),  (0, -1),          True,  (5, 30)],
        [(2, 3, 5, 5),  (0, 0, -1),       True,  (3, 5, 10)],
        [(5, 3, 4, 5),  (0, -1, 0),       True,  (3, 20, 5)],
        [(2, 3, 5, 4),  (-1, 0, 0),       True,  (6, 5, 4)],
        [(2, 3, 4, 5),  (3, -1, 0),       True,  (3, 8, 5)],
        [(2, 3, 5, 5),  (5, 3, 0, -1),    True,  (5, 3, 5, 2)],
        [(2, 3, 5, 5),  (0, 0, 0, 0),     True,  (2, 3, 5, 5)],
        [(2, 3, 5, 6),  (-2,),            True,  (2, 3, 5, 6)],
        [(2, 3, 5, 6),  (-2, 1, 30),      True,  (2, 3, 1, 30)],
        [(2, 3, 5, 6),  (-3, -3),         True,  (6, 30)],
        [(64,),         (16, 4, -4),      True,  (16, 4)],
        [(64,),         (16, -1, -4),     True,  (16, 4)],
        [(1, 2, 3, 64), (-2, -1, 16, -4), True,  (1, 2, 3, 4, 16)]]
    for test_case in test_cases:
        test_reshape_new(*test_case)
    # Test old api
    net = mx.sym.Variable("data")
    net = mx.sym.Reshape(net, target_shape=(2, 0))
    js = net.tojson()
    net = mx.sym.load_json(js)
    _, output_shape, __ = net.infer_shape(data=(2, 3, 5, 5))
    assert(output_shape[0] == (2, 75))
    # Test for Flatten
    data = mx.sym.Variable("data")
    net = mx.sym.Flatten(data)
    exe = net.simple_bind(ctx=default_context(), data=(5, 4, 3, 7))
    data_npy = np.random.normal(size=(5, 4, 3, 7))
    out_grad_npy = np.random.normal(size=(5, 4 * 3 * 7))
    outputs = exe.forward(is_train=True, data=data_npy)[0].asnumpy()
    assert_allclose(outputs, data_npy.reshape((5, 4 * 3 * 7)))
    exe.backward(out_grads=[mx.nd.array(out_grad_npy, ctx=default_context())])
    assert_allclose(exe.grad_arrays[0].asnumpy(), out_grad_npy.reshape((5, 4, 3, 7)))

def test_reduce():
    sample_num = 200
    def test_reduce_inner(numpy_reduce_func, numpy_reduce_grad_func, mx_reduce_sym, nan_prob = 0):
        for i in range(sample_num):
            # Generate random data that has ndim between 1-7 and all the shape dims between 1-5
            # Insert a NaN with probability equal to nan_prob
            ndim = np.random.randint(1, 6)
            shape = np.random.randint(1, 6, size=(ndim,))
            axis_num = np.random.randint(0, ndim, size=1)
            axis_flags = np.random.randint(0, 2, size=ndim)
            axes = []
            for (axis, flag) in enumerate(axis_flags):
                if flag:
                    axes.append(axis)
            if 0 == len(axes):
                axes = None
            elif 1 == len(axes):
                axes = axes[0]
            else:
                axes = tuple(axes)
            keepdims = np.random.randint(0, 2)
            a = mx.symbol.Variable('a')
            if axes is None:
                b = mx_reduce_sym(a, keepdims=keepdims)
            else:
                b = mx_reduce_sym(a, axis=axes, keepdims=keepdims)
            dat_npy = np.random.rand(*shape)
            if nan_prob > 0:
                dat_npy[np.random.rand(*shape) < nan_prob] = np.nan
            sum_groundtruth = np.array(numpy_reduce_func(dat_npy, axis=axes, keepdims=keepdims))
            if sum_groundtruth.shape == ():
                sum_groundtruth = np.array([sum_groundtruth])
            grad_nd = mx.nd.empty(shape)
            outgrad_npy = np.array(np.random.rand(*sum_groundtruth.shape))

            keepdim_shape = np_reduce(dat_npy, axes, 1, np.sum).shape
            grad_groundtruth = numpy_reduce_grad_func(outgrad=outgrad_npy, data=dat_npy,
                                                      outdata=sum_groundtruth,
                                                      axis=axes, keepdims=keepdims,
                                                      keepdim_shape=keepdim_shape)
            net = b.bind(default_context(), args={'a': mx.nd.array(dat_npy)},
                         args_grad={'a': grad_nd})
            net.forward(is_train=True)

            equal_forward = almost_equal_ignore_nan(net.outputs[0].asnumpy(), sum_groundtruth, 1E-4, 1E-4)
            assert equal_forward

            net.backward(out_grads=mx.nd.array(outgrad_npy))
            bc_grad_groundtruth = np.broadcast_to(grad_groundtruth, grad_nd.shape)
            equal_backward = almost_equal_ignore_nan(grad_nd.asnumpy(), bc_grad_groundtruth, 1E-4, 1E-4)
            assert equal_backward
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.sum),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        outgrad.reshape(keepdim_shape),
                      mx.symbol.sum)
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.prod),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        outgrad.reshape(keepdim_shape) * (outdata.reshape(keepdim_shape) / data),
                      mx.symbol.prod)
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.nansum),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        np.where(np.isnan(data), 0, outgrad.reshape(keepdim_shape)),
                      mx.symbol.nansum, 0.3)
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.nanprod),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        np.where(np.isnan(data), 0, outgrad.reshape(keepdim_shape) * (outdata.reshape(keepdim_shape) / data)),
                      mx.symbol.nanprod, 0.3)
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.max),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        outgrad.reshape(keepdim_shape) * (np.equal(data, outdata.reshape(keepdim_shape)).astype(np.float)),
                      mx.symbol.max)
    test_reduce_inner(lambda data, axis, keepdims:np_reduce(data, axis, keepdims, np.min),
                      lambda outgrad, data, outdata, axis, keepdims, keepdim_shape:
                        outgrad.reshape(keepdim_shape) * (np.equal(data, outdata.reshape(keepdim_shape)).astype(np.float)),
                      mx.symbol.min)

def test_broadcast():
    sample_num = 200
    for i in range(sample_num):
        # Generate random data that has ndim between 1-7 and all the shape dims between 1-5
        ndim = np.random.randint(1, 6)
        target_shape = np.random.randint(1, 6, size=(ndim,))
        axis = tuple(set(np.random.randint(0, ndim, np.random.randint(1, ndim + 1))))
        shape = target_shape.copy()
        size = tuple([shape[ele] for ele in axis])
        for ele in axis:
            shape[ele] = 1
        a = mx.symbol.Variable('a')
        sym_bcast_axis = mx.symbol.broadcast_axis(a, axis=axis, size=size)
        sym_bcast_to = mx.symbol.broadcast_to(a, shape=tuple(target_shape))
        def test_broadcasting_ele(sym_bcast):
            dat_npy = np.random.rand(*shape)
            groundtruth = dat_npy
            grad_nd = mx.nd.empty(shape)
            outgrad_npy = np.random.rand(*target_shape)
            grad_groundtruth = np_reduce(outgrad_npy, axis=axis, keepdims=True,
                                          numpy_reduce_func=np.sum)
            net = sym_bcast.bind(default_context(), args={'a': mx.nd.array(dat_npy)},
                                                 args_grad={'a': grad_nd})
            net.forward(is_train=True)
            assert (net.outputs[0].shape == target_shape).all()
            err_forward = reldiff(net.outputs[0].asnumpy(), groundtruth)
            assert err_forward < 1E-4
            net.backward(out_grads=mx.nd.array(outgrad_npy))
            err_backward = reldiff(grad_nd.asnumpy(), grad_groundtruth)
            assert err_backward < 1E-4
        test_broadcasting_ele(sym_bcast_axis)
        test_broadcasting_ele(sym_bcast_to)

def test_transpose():
    for ndim in range(1, 6):
        for t in range(5):
            dims = list(np.random.randint(1, 10, size=ndim))
            axes = list(range(ndim))
            random.shuffle(axes)
            axes = tuple(axes)
            x = mx.nd.array(np.random.normal(size=dims))
            y = mx.nd.transpose(x, axes=axes)
            assert_allclose(np.transpose(x.asnumpy(), axes=axes), y.asnumpy())

            y = mx.nd.transpose(x)
            assert_allclose(np.transpose(x.asnumpy()), y.asnumpy())


def test_expand_dims():
    for ndim in range(1, 6):
        for t in range(5):
            dims = list(np.random.randint(1, 10, size=ndim))
            axis = np.random.randint(1, ndim+1)
            x = mx.nd.array(np.random.normal(size=dims))
            y = mx.nd.expand_dims(x, axis=axis)
            assert_allclose(np.expand_dims(x.asnumpy(), axis=axis), y.asnumpy())


def test_crop():
    for ndim in range(1, 6):
        for t in range(5):
            dims = []
            begin = []
            end = []
            idx = []
            for i in range(ndim):
                d = random.randint(1, 10)
                b = random.randint(0, d-1)
                e = random.randint(b+1, d)
                dims.append(d)
                begin.append(b)
                end.append(e)
                idx.append(slice(b, e))
            x = mx.nd.array(np.random.normal(size=dims))
            y = mx.nd.crop(x, begin=tuple(begin), end=tuple(end))
            assert_allclose(x.asnumpy()[idx], y.asnumpy())


def test_slice_axis():
    for ndim in range(1, 6):
        shape = np.random.randint(1, 11, size=(ndim,))
        for t in range(ndim):
            d = shape[t]
            b = random.randint(0, d-1)
            e = random.randint(b+1, d)
            idx = []
            for i in range(ndim):
                idx.append(slice(0, shape[i]))
            idx[t] = slice(b, e)

            X = mx.symbol.Variable('X')
            x = mx.nd.array(np.random.normal(size=shape))
            Y = mx.symbol.slice_axis(data=X, axis=t, begin=b, end=e)

            xgrad = mx.nd.empty(x.shape)
            exec1 = Y.bind(default_context(), args = [x], args_grad = {'X': xgrad})
            exec1.forward()
            y = exec1.outputs[0]
            assert_allclose(x.asnumpy()[idx], y.asnumpy())
            exec1.backward([y])
            xx = x.asnumpy()
            xx[:] = 0.0
            xx[idx] = x.asnumpy()[idx]
            assert_allclose(xx, xgrad.asnumpy())


def test_flip():
    for ndim in range(1, 6):
        for t in range(5):
            dims = [random.randint(1,10) for i in range(ndim)]
            axis = random.randint(0, ndim-1)
            idx = [slice(None, None, -1) if i == axis else slice(None, None) for i in range(ndim)]
            x = mx.nd.array(np.random.normal(size=dims))
            y = mx.nd.flip(x, axis=axis)
            assert_allclose(x.asnumpy()[idx], y.asnumpy())


def test_stn():
    np.set_printoptions(threshold=np.nan)
    num_filter = 2  # conv of loc net
    kernel = (3, 3)  # conv of loc net
    num_hidden = 6  # fc of loc net
    for n in [1, 2, 3, 4]:
        for c in [1, 2, 3, 4]:
            for h in [5, 9, 13, 17]:  # for convenience test, this third and forth input dim should be 4x + 1
                for w in [5, 9, 13, 17]:
                    data_shape = (n, c, h, w)
                    target_shape = (int((data_shape[2]+1)/2), int((data_shape[3]+1)/2))
                    data = mx.sym.Variable(name="data")
                    loc = mx.sym.Convolution(data=data, kernel=kernel, pad=(1, 1), num_filter=num_filter, name="loc_conv")
                    loc = mx.sym.Flatten(data=loc)
                    loc = mx.sym.FullyConnected(data=loc, num_hidden=num_hidden, name="loc_fc")
                    stn = mx.sym.SpatialTransformer(data=data, loc=loc, target_shape=target_shape,
                                                    transform_type="affine", sampler_type="bilinear")
                    arg_names = stn.list_arguments()
                    arg_shapes, out_shapes, _ = stn.infer_shape(data=data_shape)
                    # check shape
                    assert out_shapes[0] == (data_shape[0], data_shape[1], target_shape[0], target_shape[1])
                    dev = default_context()
                    #dev = mx.gpu(0)
                    args = {}
                    args['data'] = mx.random.normal(0, 1, data_shape, ctx=mx.cpu()).copyto(dev)
                    args['loc_conv_weight'] = mx.nd.zeros((num_filter, data_shape[1], kernel[0], kernel[1]), ctx=dev)
                    args['loc_conv_bias'] = mx.nd.zeros((num_filter,), ctx=dev)
                    args['loc_fc_weight'] = mx.nd.zeros((6, num_filter*data_shape[2]*data_shape[3]), ctx=dev)
                    args['loc_fc_bias'] = mx.nd.array([0.5, 0, 0, 0, 0.5, 0], ctx=dev)
                    grad_grad = [mx.nd.zeros(shape, ctx=dev) for shape in arg_shapes]
                    exe = stn.bind(dev, args=args, args_grad=grad_grad)
                    exe.forward(is_train=True)
                    out = exe.outputs[0].asnumpy()
                    # check forward
                    reldiff(out, args['data'].asnumpy()[:, :, h//4:h-h//4, w//4:w-w//4]) < 1e-6
                    out_grad = mx.nd.ones(out.shape, ctx=dev)
                    exe.backward([out_grad])
                    # check backward
                    reldiff(out_grad.asnumpy(), grad_grad[0].asnumpy()[:, :, h//4:h-h//4, w//4:w-w//4]) < 1e-6


def test_dot(ctx=default_context()):
    # Test normal dot.
    for m in range(1, 5):
        for k in range(1, 5):
            for n in range(1, 5):
                a_npy = np.random.normal(0, 1, (m, k))
                b_npy = np.random.normal(0, 1, (k, n))
                c_npy = np.empty((m, n))
                ograd_npy = np.random.normal(0, 1, (m, n))
                agrad_npy = np.empty((m, k))
                bgrad_npy = np.empty((k, n))
                c_npy[:, :] = np.dot(a_npy[:, :], b_npy[:, :])
                bgrad_npy[:, :] = np.dot(a_npy[:, :].T, ograd_npy[:, :])
                agrad_npy[:, :] = np.dot(ograd_npy[:, :], b_npy[:, :].T)
                a = mx.sym.Variable('a')
                b = mx.sym.Variable('b')
                c = mx.sym.dot(a, b)
                exe = c.simple_bind(ctx=ctx, a=a_npy.shape, b=b_npy.shape)
                outputs = exe.forward(is_train=True, a=a_npy, b=b_npy)
                assert reldiff(outputs[0].asnumpy(), c_npy) < 1E-3
                exe.backward(out_grads=[mx.nd.array(ograd_npy, ctx=exe._ctx)])
                assert reldiff(exe.grad_dict['a'].asnumpy(), agrad_npy) < 1E-3
                assert reldiff(exe.grad_dict['b'].asnumpy(), bgrad_npy) < 1E-3
    # Test dot with transpose flag using gradient checker.
    m1_npy = np.random.normal(0, 1, (3, 4))
    m2_npy = np.random.normal(0, 1, (4, 5))
    def dot_sym():
        x = mx.sym.Variable('x')
        y = mx.sym.Variable('y')
        return mx.sym.dot(x, y)
    def dot_sym_xT():
        x = mx.sym.Variable('x')
        y = mx.sym.Variable('y')
        return mx.sym.dot(x, y, transpose_a=True)
    def dot_sym_yT():
        x = mx.sym.Variable('x')
        y = mx.sym.Variable('y')
        return mx.sym.dot(x, y, transpose_b=True)
    def dot_sym_xT_yT():
        x = mx.sym.Variable('x')
        y = mx.sym.Variable('y')
        return mx.sym.dot(x, y, transpose_a=True, transpose_b=True)
    check_numeric_gradient(dot_sym(), [m1_npy, m2_npy])
    check_numeric_gradient(dot_sym_xT(), [m1_npy.T, m2_npy])
    check_numeric_gradient(dot_sym_yT(), [m1_npy, m2_npy.T])
    check_numeric_gradient(dot_sym_xT_yT(), [m1_npy.T, m2_npy.T])

def test_batch_dot():
    for batch_size in range(1, 5):
        for m in range(1, 5):
            for k in range(1, 5):
                for n in range(1, 5):
                    transpose_a = (np.random.rand() > 0.5)
                    transpose_b = (np.random.rand() > 0.5)
                    a_npy = np.random.normal(0, 1, (batch_size, m, k))
                    b_npy = np.random.normal(0, 1, (batch_size, k, n))
                    c_npy = np.empty((batch_size, m, n))
                    ograd_npy = np.random.normal(0, 1, (batch_size, m, n))
                    agrad_npy = np.empty((batch_size, m, k))
                    bgrad_npy = np.empty((batch_size, k, n))
                    a_init_grad_npy = np.random.normal(size=(batch_size, m, k))
                    b_init_grad_npy = np.random.normal(size=(batch_size, k, n))
                    for i in range(batch_size):
                        c_npy[i, :, :] = np.dot(a_npy[i, :, :], b_npy[i, :, :])
                        bgrad_npy[i, :, :] = np.dot(a_npy[i, :, :].T, ograd_npy[i, :, :])
                        agrad_npy[i, :, :] = np.dot(ograd_npy[i, :, :], b_npy[i, :, :].T)
                    a = mx.sym.Variable('a')
                    b = mx.sym.Variable('b')
                    c = mx.sym.batch_dot(a, b, transpose_a=transpose_a, transpose_b=transpose_b)
                    if transpose_a:
                        a_npy = np.transpose(a_npy, axes=(0, 2, 1))
                        agrad_npy = np.transpose(agrad_npy, axes=(0, 2, 1))
                        a_init_grad_npy = np.transpose(a_init_grad_npy, axes=(0, 2, 1))
                    if transpose_b:
                        b_npy = np.transpose(b_npy, axes=(0, 2, 1))
                        bgrad_npy = np.transpose(bgrad_npy, axes=(0, 2, 1))
                        b_init_grad_npy = np.transpose(b_init_grad_npy, axes=(0, 2, 1))
                    exe = c.simple_bind(ctx=default_context(),
                                        a=a_npy.shape, b=b_npy.shape, grad_req='write')
                    exe_add = c.simple_bind(ctx=default_context(),
                                            a=a_npy.shape, b=b_npy.shape, grad_req='add')
                    exe_add.grad_dict['a'][:] = a_init_grad_npy
                    exe_add.grad_dict['b'][:] = b_init_grad_npy
                    outputs = exe.forward(is_train=True, a=a_npy, b=b_npy)
                    assert reldiff(outputs[0].asnumpy(), c_npy) < 1E-3
                    exe.backward(out_grads=[mx.nd.array(ograd_npy, ctx=exe._ctx)])
                    assert reldiff(exe.grad_dict['a'].asnumpy(), agrad_npy) < 1E-3
                    assert reldiff(exe.grad_dict['b'].asnumpy(), bgrad_npy) < 1E-3
                    exe_add.forward(is_train=True, a=a_npy, b=b_npy)
                    exe_add.backward(out_grads=[mx.nd.array(ograd_npy, ctx=exe._ctx)])
                    assert reldiff(exe_add.grad_dict['a'].asnumpy(),
                                   agrad_npy + a_init_grad_npy) < 1E-3
                    assert reldiff(exe_add.grad_dict['b'].asnumpy(),
                                   bgrad_npy + b_init_grad_npy) < 1E-3

def get_correlation(data1,data2,kernel_size,max_displacement,stride1,stride2,pad_size,is_multiply):

    img1 = mx.sym.Variable('img1')
    img2 = mx.sym.Variable('img2')
    return mx.sym.Correlation(data1=img1,data2=img2,kernel_size =kernel_size,max_displacement = max_displacement,
                              stride1 = stride1,stride2 = stride2,pad_size= pad_size,is_multiply = is_multiply)

def correlation_forward(data1,data2,pad_size,kernel_size,stride1,stride2,max_displacement,is_multiply):

    # compute output's dimension
    paddedbottomheight = data1.shape[2] + 2 * pad_size
    paddedbottomwidth = data1.shape[3] + 2 * pad_size
    kernel_radius = (kernel_size - 1) // 2
    border_size = max_displacement + kernel_radius
    top_width = (paddedbottomwidth - border_size * 2) // stride1
    top_height = (paddedbottomheight - border_size  * 2) // stride1
    neighborhood_grid_radius = max_displacement // stride2
    neighborhood_grid_width = neighborhood_grid_radius * 2 + 1
    top_channels = neighborhood_grid_width * neighborhood_grid_width

    out = np.zeros((data1.shape[0], top_channels, top_height, top_width))
    tmp1 = np.zeros((data1.shape[0],data1.shape[1],paddedbottomheight, paddedbottomwidth))
    tmp2 = np.zeros((data1.shape[0],data1.shape[1],paddedbottomheight, paddedbottomwidth))

    tmp1[:, :, pad_size:pad_size + data1.shape[2], pad_size:pad_size + data1.shape[3]] = data1[:,:,:,:]
    tmp2[:, :, pad_size:pad_size + data2.shape[2], pad_size:pad_size + data2.shape[3]] = data2[:,:,:,:]

    for i in range(top_height):
        for j in range(top_width):
            for nbatch in range(data1.shape[0]):

                # x1,y1 is the location in data1 , i,j is the location in output
                x1 = j * stride1 + max_displacement
                y1 = i * stride1 + max_displacement

                for top_channel in range(top_channels):

                    s2o = (top_channel % neighborhood_grid_width - neighborhood_grid_radius) * stride2
                    s2p = (top_channel // neighborhood_grid_width - neighborhood_grid_radius) * stride2

                    # location in data2
                    x2 = x1 + s2o
                    y2 = y1 + s2p

                    for h in range(kernel_size):
                        for w in range(kernel_size):
                            for channel in range(data1.shape[1]):
                                if is_multiply:
                                    out[nbatch, top_channel, i, j] += tmp1[nbatch, channel,y1 + h, x1 + w] * tmp2[nbatch, channel, y2 + h,x2 + w]
                                else:
                                    out[nbatch, top_channel, i, j] += abs(tmp1[nbatch, channel, y1 + h, x1 + w] - tmp2[nbatch, channel, y2 + h, x2 + w])
    out /= float(kernel_size**2*data1.shape[1])
    return out,tmp1,tmp2

def correlation_backward(out_grad,tmp1,tmp2,data1,data2,pad_size,kernel_size,stride1,stride2,max_displacement,is_multiply):

    # compute output's dimension
    paddedbottomheight = data1.shape[2] + 2 * pad_size
    paddedbottomwidth = data1.shape[3] + 2 * pad_size
    kernel_radius = (kernel_size - 1) // 2
    border_size = max_displacement + kernel_radius
    top_width = (paddedbottomwidth - border_size * 2) // stride1
    top_height = (paddedbottomheight - border_size  * 2) // stride1
    neighborhood_grid_radius = max_displacement // stride2
    neighborhood_grid_width = neighborhood_grid_radius * 2 + 1
    top_channels = neighborhood_grid_width * neighborhood_grid_width

    out = np.zeros((data1.shape[0], top_channels, top_height, top_width))
    tmp1_grad = np.zeros(tmp1.shape)
    tmp2_grad = np.zeros(tmp2.shape)

    for i in range(top_height):
        for j in range(top_width):
            for nbatch in range(data1.shape[0]):

                # x1,y1 is the location in data1 , i,j is the location in output
                x1 = j * stride1 + max_displacement
                y1 = i * stride1 + max_displacement

                for top_channel in range(top_channels):

                    s2o = (top_channel % neighborhood_grid_width - neighborhood_grid_radius) * stride2
                    s2p = (top_channel // neighborhood_grid_width - neighborhood_grid_radius) * stride2

                    # location in data2
                    x2 = x1 + s2o
                    y2 = y1 + s2p

                    for h in range(kernel_size):
                        for w in range(kernel_size):
                            for channel in range(data1.shape[1]):
                                if is_multiply:
                                    tmp1_grad[nbatch,channel,y1+h,x1+w]+= out_grad[nbatch,top_channel,i,j]*tmp2[nbatch, channel, y2 + h,x2 + w]
                                    tmp2_grad[nbatch,channel,y2+h,x2+w]+= out_grad[nbatch,top_channel,i,j]*tmp1[nbatch, channel, y1 + h,x1 + w]
                                else:
                                    sgn = 1 if (tmp1[nbatch, channel, y1 + h,x1 + w]>=tmp2[nbatch, channel, y2 + h,x2 + w]) else -1
                                    tmp1_grad[nbatch,channel,y1+h,x1+w]+= out_grad[nbatch,top_channel,i,j]*sgn
                                    tmp2_grad[nbatch,channel,y2+h,x2+w]+= out_grad[nbatch,top_channel,i,j]*(-sgn)

    tmp1_grad = tmp1_grad / float(kernel_size**2*data1.shape[1])
    tmp2_grad = tmp2_grad / float(kernel_size**2*data1.shape[1])
    return tmp1_grad[:,:,pad_size:pad_size+data1.shape[2],pad_size:pad_size+data1.shape[3]],tmp2_grad[:,:,pad_size:pad_size+data1.shape[2],pad_size:pad_size+data1.shape[3]],

def unittest_correlation(data_shape,kernel_size,max_displacement,stride1,stride2,pad_size,is_multiply):

    img1 = np.random.random(data_shape)
    img2 = np.random.random(data_shape)

    net1 = get_correlation(img1,img2,kernel_size,max_displacement,stride1,stride2,pad_size,is_multiply)
    net2 = get_correlation(img1,img2,kernel_size,max_displacement,stride1,stride2,pad_size,is_multiply )

    exe1 = net1.simple_bind(default_context(),img1=img1.shape,img2=img1.shape)
    exe1.arg_dict['img1'][:] = img1
    exe1.arg_dict['img2'][:] = img2

    #cpu forward
    exe1.forward()
    # python forward
    forward_result,tmp1,tmp2 = correlation_forward(img1,img2,pad_size,kernel_size,stride1,stride2,max_displacement,is_multiply)

    # forward error
    assert np.abs(exe1.outputs[0].asnumpy()-forward_result).mean() < 1e-4

    # out_grad
    a = np.ones(forward_result.shape)
    out_grad1 = mx.nd.array(a,default_context())
    # cpu backward
    exe1.backward(out_grads=out_grad1)
    # python backward
    grad1,grad2 = correlation_backward(a,tmp1,tmp2,img1,img2,pad_size,kernel_size,stride1,stride2,max_displacement,is_multiply)

    # backward error
    assert np.abs(exe1.grad_dict['img1'].asnumpy() - grad1).mean() < 1e-3
    assert np.abs(exe1.grad_dict['img2'].asnumpy() - grad2).mean() < 1e-3

def test_correlation():

    unittest_correlation((1,3,10,10), kernel_size = 1,max_displacement = 4,stride1 = 1,stride2 = 1,pad_size = 4,is_multiply = False)
    unittest_correlation((5,1,15,15), kernel_size = 1,max_displacement = 5,stride1 = 1,stride2 = 1,pad_size = 5,is_multiply = False)
    unittest_correlation((5,1,15,15), kernel_size = 1,max_displacement = 5,stride1 = 1,stride2 = 1,pad_size = 5,is_multiply = True)
    unittest_correlation((5,1,15,15), kernel_size = 1,max_displacement = 10,stride1 = 1,stride2 = 2,pad_size = 10,is_multiply = True)
    unittest_correlation((5,1,4,4), kernel_size = 3,max_displacement = 1,stride1 = 1,stride2 = 1,pad_size = 2,is_multiply = True)
    unittest_correlation((5,1,4,4), kernel_size = 3,max_displacement = 1,stride1 = 2,stride2 = 1,pad_size = 2,is_multiply = True)
    unittest_correlation((5,1,4,4), kernel_size = 3,max_displacement = 1,stride1 = 2,stride2 = 1,pad_size = 2,is_multiply = False)
    unittest_correlation((5,1,6,4), kernel_size = 3,max_displacement = 1,stride1 = 2,stride2 = 1,pad_size = 2,is_multiply = False)
    unittest_correlation((5,1,11,11), kernel_size = 5,max_displacement = 1,stride1 = 1,stride2 = 1,pad_size = 2,is_multiply = False)


def test_support_vector_machine_l1_svm():
    xpu = default_context()
    shape = (20, 10)

    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L')
    Y = mx.symbol.SVMOutput(data=X, label=L, use_linear=True)
    x = mx.nd.empty(shape, ctx = xpu)
    l = mx.nd.empty((shape[0],), ctx = xpu)
    x_np = np.random.rand(*shape)
    l_np = np.random.randint(0, shape[1], (shape[0],))
    x[:] = x_np
    l[:] = l_np

    grad = mx.nd.empty(shape, ctx = xpu)
    exec1 = Y.bind(xpu, args = [x, l], args_grad = {'X': grad})
    exec1.forward()

    assert_allclose(x_np, exec1.outputs[0].asnumpy())

    exec1.backward()

    l_mask = np.equal(l_np.reshape(shape[0],1),range(shape[1]))
    l_mask = np.array(l_mask, dtype=np.float32)*2 -1
    grad_np = (-1) * l_mask * np.greater(1 - l_mask * x_np, 0)

    assert_allclose(grad_np, grad.asnumpy())

def test_support_vector_machine_l2_svm():
    xpu = default_context()
    shape = (20, 10)

    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L')
    Y = mx.symbol.SVMOutput(data=X, label=L)
    x = mx.nd.empty(shape, ctx = xpu)
    l = mx.nd.empty((shape[0],), ctx = xpu)
    x_np = np.random.rand(*shape)
    x_np = x_np.astype(np.float32)
    l_np = np.random.randint(0, shape[1], (shape[0],))
    x[:] = x_np
    l[:] = l_np

    grad = mx.nd.empty(shape, ctx = xpu)
    exec1 = Y.bind(xpu, args = [x, l], args_grad = {'X': grad})
    exec1.forward()

    assert_allclose(x_np, exec1.outputs[0].asnumpy())

    exec1.backward()

    l_mask = np.equal(l_np.reshape(shape[0],1),range(shape[1]))
    l_mask = np.array(l_mask, dtype=np.float32)*2 -1
    grad_np = (-2)*l_mask*np.maximum(1-l_mask*x_np,0)
    grad_np = grad_np.astype(np.float32)
    assert_allclose(grad_np, grad.asnumpy())

def test_roipooling():
    data = mx.symbol.Variable(name='data')
    rois = mx.symbol.Variable(name='rois')
    test = mx.symbol.ROIPooling(data=data, rois=rois, pooled_size=(6, 6), spatial_scale=1)

    x1 = np.random.rand(4, 3, 12, 8)
    x2 = np.array([[0, 1, 1, 6, 6], [2, 6, 2, 7, 11], [1, 3, 1, 5, 10], [0, 3, 3, 3, 3]])

    check_numeric_gradient(test, [x1, x2], numeric_eps=1e-3, check_eps=1e-2)
    check_numeric_gradient(sym=test, location=[x1, x2],
                           grad_nodes={'data':'add', 'rois':'write'},
                           numeric_eps=1e-3, check_eps=1e-2)

def check_pad_with_shape(shape, xpu, pad_width, mode):
    # bind with label
    X = mx.symbol.Variable('X')
    Y = mx.symbol.Pad(data=X, mode=mode, pad_width=pad_width)
    x = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    # numpy result
    pad_grouped = list(zip(*[iter(list(pad_width))] * 2))
    np_out = np.pad(x.asnumpy(), pad_grouped, mode)
    # mxnet result
    grad = mx.nd.empty(shape, ctx = xpu)
    exec1 = Y.bind(xpu, args = [x], args_grad = {'X': grad})
    exec1.forward()
    out = exec1.outputs[0].asnumpy()
    # compare numpy + mxnet
    assert_allclose(out, np_out, rtol=1e-5)
    # grad check
    check_numeric_gradient(Y, [x.asnumpy()], numeric_eps=1e-3, check_eps=1e-2)

def test_pad():
    shape1 = (2, 3, 2, 3)
    pad1 = (0, 0, 0, 0, 1, 2, 3, 4)
    shape2 = (2, 3, 2, 3, 3)
    pad2 = (0, 0, 0, 0, 1, 2, 3, 4, 3, 1)
    check_pad_with_shape(shape1, default_context(), pad1, 'constant')
    check_pad_with_shape(shape1, default_context(), pad1, 'edge')
    check_pad_with_shape(shape2, default_context(), pad2, 'constant')
    check_pad_with_shape(shape2, default_context(), pad2, 'edge')

def np_instance_norm(data, weight, bias, eps):
    spatial_dims = data.shape[2::]
    num_spatial_vals = np.prod(np.array(spatial_dims))
    scale = 1/float(num_spatial_vals)
    sum_axis = tuple(range(2, data.ndim))
    mean = scale * np.sum(data, axis = sum_axis)
    mean = np.reshape(np.repeat(mean, num_spatial_vals), data.shape)
    var = scale * np.sum((data - mean)**2, axis = sum_axis)
    var = np.reshape(np.repeat(var, num_spatial_vals), data.shape)

    weightBatch = np.tile(weight, (data.shape[0], 1))
    weightBatch = np.reshape(np.repeat(weightBatch, num_spatial_vals), data.shape)
    biasBatch = np.tile(bias, (data.shape[0], 1))
    biasBatch = np.reshape(np.repeat(biasBatch, num_spatial_vals), data.shape)
    return weightBatch * (data - mean)/np.sqrt(var + eps) + biasBatch

def check_instance_norm_with_shape(shape, xpu):
    # bind with label
    eps = 0.0234
    X = mx.symbol.Variable('X')
    G = mx.symbol.Variable('G')
    B = mx.symbol.Variable('B')

    Y = mx.symbol.InstanceNorm(data=X, beta=B, gamma=G, eps=eps)
    x = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    gamma = mx.random.uniform(-1, 1, shape[1], ctx=mx.cpu()).copyto(xpu)
    beta = mx.random.uniform(-1, 1, shape[1], ctx=mx.cpu()).copyto(xpu)

    np_out = np_instance_norm(x.asnumpy(), gamma.asnumpy(), beta.asnumpy(), eps)
    exec1 = Y.bind(xpu, args = {'X':x, 'G':gamma, 'B':beta})
    exec1.forward(is_train=False)
    out = exec1.outputs[0].asnumpy()
    assert_allclose(out, np_out, rtol=1e-4)
    check_numeric_gradient(Y, {'X':x.asnumpy(), 'G':gamma.asnumpy(), 'B':beta.asnumpy()}, numeric_eps=1e-2, check_eps=0.16)

def test_instance_normalization():
    check_instance_norm_with_shape((2,4,5,6), default_context())
    check_instance_norm_with_shape((3,3,2,3,2,1,1), default_context())

def check_l2_normalization(in_shape, mode, ctx=default_context(), norm_eps=1e-10):
    data = mx.symbol.Variable('data')
    out = mx.symbol.L2Normalization(data=data, mode=mode, eps=norm_eps)
    np.random.seed()
    in_data = np.random.uniform(-1, 1, in_shape)
    # calculate numpy results
    if mode == 'channel':
        assert in_data.ndim > 2
        np_norm = np.linalg.norm(in_data, axis=1) + norm_eps
        np_norm = np.repeat(1. / np.expand_dims(np_norm, axis=1), in_data.shape[1], axis=1)
        np_out = np.multiply(in_data, np_norm)
    elif mode == 'spatial':
        assert in_data.ndim > 2
        s = in_data.shape
        np_norm = np.linalg.norm(in_data.reshape((s[0], s[1], -1)), axis=2) + norm_eps
        np_norm = np.repeat(1. / np_norm[:, np.newaxis], in_data.size / s[0] / s[1], axis=2)
        np_out = np.multiply(in_data, np_norm.reshape(s))
    elif mode == 'instance':
        assert in_data.ndim > 1
        s = in_data.shape
        np_norm = np.linalg.norm(in_data.reshape((s[0], -1)), axis=1) + norm_eps
        np_norm = np.repeat(1. / np_norm[:, np.newaxis], in_data.size / s[0], axis=1)
        np_out = np.multiply(in_data, np_norm.reshape(s))
    else:
        raise RuntimeError('Unknown l2 normalization mode')
    exe = out.simple_bind(ctx=ctx, data=in_data.shape)
    output = exe.forward(is_train=True, data=in_data)
    # compare numpy + mxnet
    assert_allclose(exe.outputs[0].asnumpy(), np_out, rtol=1e-5)
    # check gradient
    check_numeric_gradient(out, [in_data], numeric_eps=1e-3, check_eps=1e-2)

def test_l2_normalization():
    for mode in ['channel', 'spatial', 'instance']:
        for nbatch in [1, 4]:
            for nchannel in [3, 5]:
                for height in [4, 6]:
                    check_l2_normalization((nbatch, nchannel, height), mode)
                    for width in [5, 7]:
                        check_l2_normalization((nbatch, nchannel, height, width), mode)

def sequence_mask_numpy(array, lengths, value):
    arrayMask = array.copy()
    shape = array.shape
    batch = shape[1]
    for i in range(batch):
        arrayMask[int(lengths[i]):, i] = value 
    return arrayMask

def check_sequence_mask(shape, xpu, mask_value):
    # bind with label
    X = mx.symbol.Variable('X')
    L = mx.symbol.Variable('L') # lengths
    Y = mx.symbol.SequenceMask(data=X, use_sequence_length=True, sequence_length=L, value=mask_value)
    x = mx.random.uniform(-1, 1, shape, ctx=mx.cpu()).copyto(xpu)
    l = mx.nd.array(np.random.randint(1, shape[0] + 1, shape[1]), ctx=mx.cpu()).copyto(xpu)

    # numpy result
    np_out = sequence_mask_numpy(x.asnumpy(), l.asnumpy(), mask_value)
    # mxnet result
    gradX = mx.nd.empty(shape, ctx = xpu)
    gradL = mx.nd.empty((shape[1]), ctx = xpu)
    exec1 = Y.bind(xpu, args = [x, l], grad_req={'X':'write', 'L':'null'}, args_grad = {'X':gradX, 'L':gradL})
    exec1.forward()
    out = exec1.outputs[0].asnumpy()
    # compare numpy + mxnet
    assert_allclose(out, np_out, rtol=1e-5)
    # grad check
    check_numeric_gradient(Y, [x.asnumpy(), l.asnumpy()], grad_nodes={'X':'write'},
        numeric_eps=1e-3, check_eps=1)

def test_sequence_mask():
    shape1 = (4, 2, 2, 3)
    shape2 = (1, 2, 2, 3, 1, 1)
    check_sequence_mask(shape1, default_context(), 2.1)
    check_sequence_mask(shape2, default_context(), 0.1)

def mathematical_core_binary(name,
                             forward_mxnet_call,
                             forward_numpy_call,
                             backward_numpy_call1,
                             backward_numpy_call2,
                             data1_init=2.,
                             data2_init=3.,
                             grad_init=2.):
    data1 = mx.symbol.Variable('data')
    data2 = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp1 = np.random.rand(3, 4)
    data_tmp2 = np.random.rand(3, 4)
    data_tmp1[:] = data1_init
    data_tmp2[:] = data2_init

    arr_data1 = mx.nd.array(data_tmp1)
    arr_data2 = mx.nd.array(data_tmp2)

    arr_grad1 = mx.nd.empty(shape)
    arr_grad2 = mx.nd.empty(shape)

    test = forward_mxnet_call(data1, data2)
    exe_test = test.bind(default_context(), args=[arr_data1, arr_data2], args_grad=[arr_grad1, arr_grad2])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = forward_numpy_call(data_tmp1, data_tmp2)
    assert reldiff(out, npout) < 1e-6, "%s mathematical forward failed\n%s\n\n%s" % (name, out, npout)

    out_grad = mx.nd.empty(shape)
    out_grad[:] = grad_init
    exe_test.backward(out_grad)

    npout_grad = np.ones(shape)
    npout_grad[:] = grad_init

    npout_grad1 = npout_grad * backward_numpy_call1(data_tmp1, data_tmp2)
    npout_grad2 = npout_grad * backward_numpy_call2(data_tmp1, data_tmp2)
    arr_grad1 = arr_grad1.asnumpy()
    arr_grad2 = arr_grad2.asnumpy()

    assert reldiff(arr_grad1, npout_grad1) < 1e-6, "%s mathematical backward1 failed\n%s\n\n%s" % (
        name, arr_grad1, npout_grad)
    assert reldiff(arr_grad2, npout_grad2) < 1e-6, "%s mathematical backward2 failed\n%s\n\n%s" % (
        name, arr_grad2, npout_grad)

def mathematical_core(name, forward_mxnet_call, forward_numpy_call, backward_numpy_call, data_init=5., grad_init=2.):
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:] = data_init
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:] = 3

    test = forward_mxnet_call(data)
    exe_test = test.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = forward_numpy_call(data_tmp)
    assert reldiff(out, npout) < 1e-6, "%s mathematical forward failed\n%s\n\n%s" % (name, out, npout)

    out_grad = mx.nd.empty(shape)
    out_grad[:] = grad_init
    npout_grad = out_grad.asnumpy()
    temp = backward_numpy_call(data_tmp)
    npout_grad = npout_grad * temp
    exe_test.backward(out_grad)
    arr_grad = arr_grad.asnumpy()
    # print(name)
    # print(arr_grad)
    # print(npout_grad)
    assert reldiff(arr_grad, npout_grad) < 1e-6, "%s mathematical backward failed\n%s\n\n%s" % (
        name, arr_grad, npout_grad)

def test_special_functions_using_scipy():
    try:
        from scipy import special as scipy_special
    except:
        print("Could not import scipy. Skipping unit tests for special functions")
        return

    # gamma
    mathematical_core("gamma", lambda x: mx.sym.gamma(x), lambda x: scipy_special.gamma(x),
                     lambda x: scipy_special.gamma(x) * scipy_special.psi(x), 0.5, 0.5)

    # gammaln
    mathematical_core("gammaln", lambda x: mx.sym.gammaln(x), lambda x: scipy_special.gammaln(x),
                     lambda x: scipy_special.psi(x), 0.5, 0.5)



def mathematical_core_binary(name,
                             forward_mxnet_call,
                             forward_numpy_call,
                             backward_numpy_call1,
                             backward_numpy_call2,
                             data1_init=2.,
                             data2_init=3.,
                             grad_init=2.):
    data1 = mx.symbol.Variable('data')
    data2 = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp1 = np.random.rand(3, 4)
    data_tmp2 = np.random.rand(3, 4)
    data_tmp1[:] = data1_init
    data_tmp2[:] = data2_init

    arr_data1 = mx.nd.array(data_tmp1)
    arr_data2 = mx.nd.array(data_tmp2)

    arr_grad1 = mx.nd.empty(shape)
    arr_grad2 = mx.nd.empty(shape)

    test = forward_mxnet_call(data1, data2)
    exe_test = test.bind(default_context(), args=[arr_data1, arr_data2], args_grad=[arr_grad1, arr_grad2])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = forward_numpy_call(data_tmp1, data_tmp2)
    assert reldiff(out, npout) < 1e-6, "%s mathematical forward failed\n%s\n\n%s" % (name, out, npout)

    out_grad = mx.nd.empty(shape)
    out_grad[:] = grad_init
    exe_test.backward(out_grad)

    npout_grad = np.ones(shape)
    npout_grad[:] = grad_init

    npout_grad1 = npout_grad * backward_numpy_call1(data_tmp1, data_tmp2)
    npout_grad2 = npout_grad * backward_numpy_call2(data_tmp1, data_tmp2)
    arr_grad1 = arr_grad1.asnumpy()
    arr_grad2 = arr_grad2.asnumpy()

    assert reldiff(arr_grad1, npout_grad1) < 1e-6, "%s mathematical backward1 failed\n%s\n\n%s" % (
        name, arr_grad1, npout_grad)
    assert reldiff(arr_grad2, npout_grad2) < 1e-6, "%s mathematical backward2 failed\n%s\n\n%s" % (
        name, arr_grad2, npout_grad)


def mathematical_core(name, forward_mxnet_call, forward_numpy_call, backward_numpy_call, data_init=5., grad_init=2.):
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:] = data_init
    arr_data = mx.nd.array(data_tmp)
    arr_grad = mx.nd.empty(shape)
    arr_grad[:] = 3

    test = forward_mxnet_call(data)
    exe_test = test.bind(default_context(), args=[arr_data], args_grad=[arr_grad])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = forward_numpy_call(data_tmp)
    assert reldiff(out, npout) < 1e-5, "%s mathematical forward failed\n%s\n\n%s" % (name, out, npout)

    out_grad = mx.nd.empty(shape)
    out_grad[:] = grad_init
    npout_grad = out_grad.asnumpy()
    temp = backward_numpy_call(data_tmp)
    npout_grad = npout_grad * temp
    exe_test.backward(out_grad)
    arr_grad = arr_grad.asnumpy()
    # print(name)
    # print(arr_grad)
    # print(npout_grad)
    assert reldiff(arr_grad, npout_grad) < 1e-5, "%s mathematical backward failed\n%s\n\n%s" % (
        name, arr_grad, npout_grad)


def rounding(name, forward_mxnet_call, forward_numpy_call, data_init=5., grad_init=2.):
    data = mx.symbol.Variable('data')
    shape = (3, 4)
    data_tmp = np.ones(shape)
    data_tmp[:] = data_init
    arr_data = mx.nd.array(data_tmp)

    test = forward_mxnet_call(data)
    exe_test = test.bind(default_context(), args=[arr_data])
    exe_test.forward()
    out = exe_test.outputs[0].asnumpy()
    npout = forward_numpy_call(data_tmp)
    assert reldiff(out, npout) < 1e-6, "%s mathematical forward failed\n%s\n\n%s" % (name, out, npout)

def test_mathematical():
    # rsqrt
    mathematical_core("rsqrt",
                      lambda x: mx.sym.rsqrt(x),
                      lambda x: 1 / np.sqrt(x),
                      lambda x: -(1.0 / (2.0 * x * np.sqrt(x))))
    # tan
    mathematical_core("tan", lambda x: mx.sym.tan(x), lambda x: np.tan(x), lambda x: np.tan(x) ** 2 + 1)
    # arcsin
    mathematical_core("arcsin", lambda x: mx.sym.arcsin(x), lambda x: np.arcsin(x),
                      lambda x: 1. / (1. - x ** 2) ** (1. / 2.), 0.5, 0.5)
    # arccos
    mathematical_core("arccos", lambda x: mx.sym.arccos(x), lambda x: np.arccos(x),
                      lambda x: -1. / (1. - x ** 2.) ** (1. / 2.), 0.5, 0.5)
    # arctan
    mathematical_core("arctan", lambda x: mx.sym.arctan(x), lambda x: np.arctan(x),
                      lambda x: 1. / (x ** 2. + 1.), 0.5, 0.5)
    # hypot
    mathematical_core_binary("hypot",
                             lambda x, y: mx.sym.hypot(x, y),
                             lambda x, y: np.hypot(x, y),
                             lambda x, y: x / np.hypot(x, y),
                             lambda x, y: y / np.hypot(x, y),
                             0.5, 0.5, 0.5)

    # hypot scalar
    mathematical_core("hypot scalar",
                      lambda x: mx.sym.hypot(x, 3),
                      lambda x: np.hypot(x, 3),
                      lambda x: x / np.hypot(x, 3),
                      0.5, 0.5)

    # degrees
    mathematical_core("degrees",
                      lambda x: mx.sym.degrees(x),
                      lambda x: np.degrees(x),
                      lambda x: 180./np.pi,
                      0.5, 0.5)
    # radians
    mathematical_core("radians",
                      lambda x: mx.sym.radians(x),
                      lambda x: np.radians(x),
                      lambda x: np.pi / 180.,
                      0.6, 1)
    # sinh
    mathematical_core("sinh", lambda x: mx.sym.sinh(x), lambda x: np.sinh(x), lambda x: np.cosh(x))

    # cosh
    mathematical_core("cosh", lambda x: mx.sym.cosh(x), lambda x: np.cosh(x), lambda x: np.sinh(x), 5, 5)

    # tanh
    mathematical_core("tanh", lambda x: mx.sym.tanh(x), lambda x: np.tanh(x), lambda x: 1. - np.tanh(x) ** 2, 0.5, 1)

    # arcsinh
    mathematical_core("arcsinh", lambda x: mx.sym.arcsinh(x), lambda x: np.arcsinh(x),
                      lambda x: 1./(x**2 + 1.)**(1./2.))

    # arccosh
    mathematical_core("arccosh", lambda x: mx.sym.arccosh(x), lambda x: np.arccosh(x),
                      lambda x: 1./(x**2 - 1.)**(1./2.))

    # arctanh
    mathematical_core("arctanh", lambda x: mx.sym.arctanh(x), lambda x: np.arctanh(x),
                      lambda x: -1./(x**2 - 1.), 0.5)

    # log1p
    mathematical_core("log1p", lambda x: mx.sym.log1p(x), lambda x: np.log1p(x),
                      lambda x: 1. / (1.0 + x), 0.5, 0.5)
    # expm1
    mathematical_core("expm1", lambda x: mx.sym.expm1(x), lambda x: np.expm1(x),
                      lambda x: np.exp(x), 0.5, 0.5)

    # log10
    mathematical_core("log10", lambda x: mx.sym.log10(x), lambda x: np.log10(x),
                      lambda x: (1 / x))

    # log2
    mathematical_core("log2", lambda x: mx.sym.log2(x), lambda x: np.log2(x),
                      lambda x: (1 / x))

    # rint
    rounding("rint", lambda x: mx.sym.rint(x), lambda x: np.rint(x))

    # fix
    rounding("fix", lambda x: mx.sym.fix(x), lambda x: np.fix(x))

def test_special_functions_using_scipy():
    try:
        from scipy import special as scipy_special
    except:
        print("Could not import scipy. Skipping unit tests for special functions")
        return

    # gamma
    mathematical_core("gamma", lambda x: mx.sym.gamma(x), lambda x: scipy_special.gamma(x),
                     lambda x: scipy_special.gamma(x) * scipy_special.psi(x), 0.5, 0.5)

    # gammaln
    mathematical_core("gammaln", lambda x: mx.sym.gammaln(x), lambda x: scipy_special.gammaln(x),
                     lambda x: scipy_special.psi(x), 0.5, 0.5)


def test_init():
    def test_basic_val_init(sym_func, np_func, shape, dtype):
        x = sym_func(shape=shape, dtype=dtype)
        exe = x.bind(default_context(), args=[], args_grad=[])
        exe.forward()
        assert_allclose(exe.outputs[0].asnumpy(), np_func(shape=shape, dtype=dtype))
        assert exe.outputs[0].asnumpy().dtype == dtype
    def test_arange():
        for i in range(5):
            start = np.random.rand() * 10
            stop = start + np.random.rand() * 100
            step = np.random.rand() * 4
            repeat = int(np.random.rand() * 5) + 1
            gt = np.arange(start=start, stop=stop, step=step)
            gt = np.broadcast_to(gt.reshape((gt.shape[0], 1)), shape=(gt.shape[0], repeat)).ravel()
            x = mx.sym.arange(start=start, stop=stop, step=step, repeat=repeat)
            exe = x.simple_bind(ctx=default_context())
            assert len(exe.grad_arrays) == 0
            pred = exe.forward(is_train=False)[0].asnumpy()
            assert_almost_equal(pred, gt, default_numerical_threshold())
    test_basic_val_init(mx.sym.zeros, np.zeros, (3, 4), np.float32)
    test_basic_val_init(mx.sym.ones, np.ones, 3, np.int32)
    test_basic_val_init(mx.sym.ones, np.ones, (2, 2, 3), np.float16)
    test_arange()


def test_order(ctx=default_context()):
    def gt_topk(dat, axis, ret_typ, k, is_ascend):
        if ret_typ == "indices":
            if is_ascend:
                indices = np.arange(k)
            else:
                indices = np.arange(-1, -k-1, -1)
            ret = np.take(dat.argsort(axis=axis), axis=axis, indices=indices, mode='wrap')
        elif ret_typ == "value":
            if is_ascend:
                indices = np.arange(k)
            else:
                indices = np.arange(-1, -k-1, -1)
            ret = np.take(np.sort(dat, axis=axis), axis=axis, indices=indices, mode='wrap')
        else:
            assert dat.shape == (5, 5, 5, 5)
            assert axis is None or axis ==1
            ret = np.zeros(dat.shape)
            if is_ascend:
                indices = np.arange(k)
            else:
                indices = np.arange(-1, -k-1, -1)
            gt_argsort = np.take(dat.argsort(axis=axis), axis=axis, indices=indices, mode='wrap')
            if axis is None:
                ret.ravel()[gt_argsort] = 1
            else:
                for i in range(5):
                    for j in range(5):
                        for k in range(5):
                            ret[i, gt_argsort[i, :, j, k], j, k] = 1
        return ret
    a_npy = np.random.normal(size=(5, 5, 5, 5))
    a = mx.sym.Variable('a')
    b = mx.sym.topk(a, axis=1, is_ascend=False, ret_typ="value", k=2)
    check_numeric_gradient(b, location={'a': a_npy}, numeric_eps=1e-3, ctx=ctx)
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="value", k=2,
                                             is_ascend=False)])
    b = mx.sym.topk(a, axis=None, is_ascend=True, ret_typ="value", k=10)
    check_numeric_gradient(b, location={'a': a_npy}, numeric_eps=1e-4, check_eps=2E-2, ctx=ctx)
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=None, ret_typ="value", k=10,
                                             is_ascend=True)])
    b = mx.sym.topk(a, axis=3, is_ascend=True, ret_typ="value", k=3)
    check_numeric_gradient(b, location={'a': a_npy}, numeric_eps=1e-3, ctx=ctx)
    check_numeric_gradient(b, location={'a': a_npy}, numeric_eps=1e-3, ctx=ctx,
                           grad_nodes={'a': 'add'})
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=3, ret_typ="value", k=3,
                                             is_ascend=True)])
    b = mx.sym.topk(a, axis=3, is_ascend=False, ret_typ="indices", k=3)
    check_symbolic_backward(sym=b, location={'a': a_npy},
                            out_grads=[np.random.normal(size=(5, 5, 5, 3))],
                            expected=[np.zeros((5, 5, 5, 5))])
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=3, ret_typ="indices", k=3,
                                             is_ascend=False)])
    b = mx.sym.topk(a, axis=1, is_ascend=True, ret_typ="mask", k=3)
    check_symbolic_backward(sym=b, location={'a': a_npy},
                            out_grads=[np.random.normal(size=(5, 5, 5, 5))],
                            expected=[np.zeros((5, 5, 5, 5))])
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="mask", k=3,
                                             is_ascend=True)])
    a = mx.sym.Variable('a')
    b = mx.sym.sort(a, axis=1, is_ascend=False)
    check_numeric_gradient(b, location={'a': a_npy}, numeric_eps=1e-3, ctx=ctx)
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="value", k=5,
                                             is_ascend=False)])
    a = mx.sym.Variable('a')
    b = mx.sym.argsort(a, axis=1, is_ascend=False)
    check_symbolic_backward(sym=b, location={'a': a_npy},
                            out_grads=[np.random.normal(size=(5, 5, 5, 5))],
                            expected=[np.zeros((5, 5, 5, 5))])
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="indices", k=5,
                                             is_ascend=False)])
    a = mx.sym.Variable('a')
    b = mx.sym.argmax(a, axis=1, keepdims=True)
    check_symbolic_backward(sym=b, location={'a': a_npy},
                            out_grads=[np.random.normal(size=(5, 5, 5, 5))],
                            expected=[np.zeros((5, 5, 5, 5))])
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="indices", k=1,
                                             is_ascend=False)])
    a = mx.sym.Variable('a')
    b = mx.sym.argmin(a, axis=1, keepdims=True)
    check_symbolic_backward(sym=b, location={'a': a_npy},
                            out_grads=[np.random.normal(size=(5, 5, 5, 5))],
                            expected=[np.zeros((5, 5, 5, 5))])
    check_symbolic_forward(b, location={'a': a_npy},
                           expected=[gt_topk(dat=a_npy, axis=1, ret_typ="indices", k=1,
                                             is_ascend=True)])


def test_blockgrad():
    a = mx.sym.Variable('a')
    b = mx.sym.BlockGrad(a)
    exe = b.simple_bind(ctx=default_context(), a=(10, 10))
    a_npy = np.random.rand(10, 10)
    exe.forward(is_train=True, a=a_npy)
    assert_almost_equal(exe.outputs[0].asnumpy(), a_npy)
    exe.backward()  # No error if BlockGrad works

def test_take():
    def check_output_n_grad(data_shape, idx_shape):
        exe = result.simple_bind(default_context(), a=data_shape, 
                                 indices=idx_shape)
        data_real = np.random.normal(size=data_shape).astype('float32')
        idx_real = np.random.randint(low=0, high=data_shape[0], size=idx_shape)
        grad_out = np.ones(idx_shape + data_shape[1:], dtype='float32')
        grad_in = np.zeros(data_shape, dtype='float32')

        exe.arg_dict['a'][:] = mx.nd.array(data_real)
        exe.arg_dict['indices'][:] = mx.nd.array(idx_real)
        exe.forward()
        assert reldiff(exe.outputs[0].asnumpy(), data_real[idx_real]) < 1e-6

        for i in np.nditer(idx_real):
            grad_in[i] += 1.0

        exe.backward([mx.nd.array(grad_out)])
        assert reldiff(exe.grad_dict['a'].asnumpy(), grad_in) < 1e-6

    data = mx.sym.Variable('a')
    idx = mx.sym.Variable('indices')
    idx = mx.sym.BlockGrad(idx)
    result = mx.sym.take(a=data, indices=idx)

    for data_ndim in range(2, 5):
        for idx_ndim in range(1, 4):
            data_shape = ()
            for _ in range(data_ndim):
                data_shape += (np.random.randint(low=3, high=6), )
            idx_shape = ()
            for _ in range(idx_ndim):
                idx_shape += (np.random.randint(low=3, high=5), ) 
            check_output_n_grad(data_shape, idx_shape)

def test_index2d():
    for _ in range(30):
        n = np.random.randint(1, 100)
        m = np.random.randint(1, 500)
        data = mx.random.uniform(-1, 1, shape=(n, m), ctx=default_context())
        x = mx.nd.array(np.random.randint(0, m, size=n), ctx=default_context(), dtype='int32')
        r = mx.nd.batch_take(data, x)
        assert_almost_equal(r.asnumpy(), data.asnumpy()[np.arange(n), x.asnumpy()])

if __name__ == '__main__':
    test_index2d()
    test_init()
    test_expand_dims()
    test_slice_axis()
    test_softmax()
    test_broadcast_binary_op()
    test_flip()
    test_crop()
    test_transpose()
    test_convolution_grouping()
    test_nearest_upsampling()
    test_binary_op_duplicate_input()
    test_elementwise_sum()
    test_concat()
    test_slice_channel()
    test_regression()
    test_python_op()
    test_swapaxes()
    test_scalarop()
    test_scalar_pow()
    test_symbol_pow()
    test_pow_fn()
    test_embedding()
    test_rsqrt_cos_sin()
    test_maximum_minimum()
    test_maximum_minimum_scalar()
    test_abs()
    test_round_ceil_floor()
    test_deconvolution()
    test_batchnorm_training()
    check_softmax_with_ignore_label(default_context())
    test_convolution_dilated_impulse_response()
    test_reshape()
    test_reduce()
    test_broadcast()
    test_stn()
    test_dot()
    test_batch_dot()
    test_correlation()
    test_support_vector_machine_l1_svm()
    test_support_vector_machine_l2_svm()
    test_roipooling()
    test_pad()
    test_instance_normalization()
    test_l2_normalization()
    test_sequence_mask()
    test_mathematical()
    test_special_functions_using_scipy()
    test_order()
    test_blockgrad()
    test_take()
    test_binary_logic()
