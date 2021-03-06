import sys
import theano
import theano.tensor as T
import numpy as np
import matplotlib.pyplot as plt
import json

from datetime import datetime
from sklearn.utils import shuffle
from util import init_weight, get_wikipedia_data


class GRU:
    def __init__(self, Mi, Mo, activation):
        self.Mi = Mi
        self.Mo = Mo
        self.f  = activation

        # numpy init
        Wxr = init_weight(Mi, Mo)
        Whr = init_weight(Mo, Mo)
        br  = np.zeros(Mo)
        Wxz = init_weight(Mi, Mo)
        Whz = init_weight(Mo, Mo)
        bz  = np.zeros(Mo)
        Wxh = init_weight(Mi, Mo)
        Whh = init_weight(Mo, Mo)
        bh  = np.zeros(Mo)
        h0  = np.zeros(Mo)

        # theano vars
        self.Wxr = theano.shared(Wxr)
        self.Whr = theano.shared(Whr)
        self.br  = theano.shared(br)
        self.Wxz = theano.shared(Wxz)
        self.Whz = theano.shared(Whz)
        self.bz  = theano.shared(bz)
        self.Wxh = theano.shared(Wxh)
        self.Whh = theano.shared(Whh)
        self.bh  = theano.shared(bh)
        self.h0  = theano.shared(h0)
        self.params = [self.Wxr, self.Whr, self.br, self.Wxz, self.Whz, self.bz, self.Wxh, self.Whh, self.bh, self.h0]

    def recurrence(self, x_t, h_t1):
        r = T.nnet.sigmoid(x_t.dot(self.Wxr) + h_t1.dot(self.Whr) + self.br)
        z = T.nnet.sigmoid(x_t.dot(self.Wxz) + h_t1.dot(self.Whz) + self.bz)
        hhat = self.f(x_t.dot(self.Wxh) + (r * h_t1).dot(self.Whh) + self.bh)
        h = (1 - z) * h_t1 + z * hhat
        return h

    def output(self, x):
        # input X should be a matrix (2-D)
        # rows index time
        h, _ = theano.scan(
            fn=self.recurrence,
            sequences=x,
            outputs_info=[self.h0],
            n_steps=x.shape[0],
        )
        return h

class RNN:
    def __init__(self, D, hidden_layer_sizes, V):
        self.hidden_layer_sizes = hidden_layer_sizes
        self.D = D
        self.V = V

    def fit(self, X, learning_rate=10e-5, mu=0.99, epochs=10, show_fig=True, activation=T.nnet.relu, RecurrentUnit=GRU, normalize=True):
        D = self.D
        V = self.V
        N = len(X)

        We = init_weight(V, D)
        self.hidden_layers = []
        Mi = D
        for Mo in self.hidden_layer_sizes:
            ru = RecurrentUnit(Mi, Mo, activation)
            self.hidden_layers.append(ru)
            Mi = Mo

        Wo = init_weight(Mi, V)
        bo = np.zeros(V)

        self.We = theano.shared(We)
        self.Wo = theano.shared(Wo)
        self.bo = theano.shared(bo)
        self.params = [self.Wo, self.bo]
        for ru in self.hidden_layers:
            self.params += ru.params

        thX = T.ivector('X')
        thY = T.ivector('Y')

        Z = self.We[thX]
        for ru in self.hidden_layers:
            Z = ru.output(Z)
        py_x = T.nnet.softmax(Z.dot(self.Wo) + self.bo)

        prediction = T.argmax(py_x, axis=1)
        # let's return py_x too so we can draw a sample instead
        self.predict_op = theano.function(
            inputs=[thX],
            outputs=[py_x, prediction],
            allow_input_downcast=True,
        )
        
        cost = -T.mean(T.log(py_x[T.arange(thY.shape[0]), thY]))
        grads = T.grad(cost, self.params)
        dparams = [theano.shared(p.get_value()*0) for p in self.params]

        dWe = theano.shared(self.We.get_value()*0)
        gWe = T.grad(cost, self.We)
        dWe_update = mu*dWe - learning_rate*gWe
        We_update = self.We + dWe_update
        if normalize:
            We_update /= We_update.sum(axis=1).dimshuffle(0, 'x')

        updates = [
            (p, p + mu*dp - learning_rate*g) for p, dp, g in zip(self.params, dparams, grads)
        ] + [
            (dp, mu*dp - learning_rate*g) for dp, g in zip(dparams, grads)
        ] + [
            (self.We, We_update), (dWe, dWe_update)
        ]

        self.train_op = theano.function(
            inputs=[thX, thY],
            outputs=[cost, prediction],
            updates=updates
        )

        costs = []
        for i in xrange(epochs):
            t0 = datetime.now()
            X = shuffle(X)
            n_correct = 0
            n_total = 0
            cost = 0
            for j in xrange(N):
                if np.random.random() < 0.01 or len(X[j]) <= 1:
                    input_sequence = [0] + X[j]
                    output_sequence = X[j] + [1]
                else:
                    input_sequence = [0] + X[j][:-1]
                    output_sequence = X[j]
                n_total += len(output_sequence)

                # test:
                
                try:
                    # we set 0 to start and 1 to end
                    c, p = self.train_op(input_sequence, output_sequence)
                except Exception as e:
                    PYX, pred = self.predict_op(input_sequence)
                    print "input_sequence len:", len(input_sequence)
                    print "PYX.shape:",PYX.shape
                    print "pred.shape:", pred.shape
                    raise e
                # print "p:", p
                cost += c
                # print "j:", j, "c:", c/len(X[j]+1)
                for pj, xj in zip(p, output_sequence):
                    if pj == xj:
                        n_correct += 1
                if j % 200 == 0:
                    sys.stdout.write("j/N: %d/%d correct rate so far: %f\r" % (j, N, float(n_correct)/n_total))
                    sys.stdout.flush()
            print "i:", i, "cost:", cost, "correct rate:", (float(n_correct)/n_total), "time for epoch:", (datetime.now() - t0)
            costs.append(cost)

        if show_fig:
            plt.plot(costs)
            plt.show()


def train_wikipedia(we_file='word_embeddings.npy', w2i_file='wikipedia_word2idx.json'):
    # there are 32 files
    sentences, word2idx = get_wikipedia_data(n_files=32, n_vocab=2000)
    print "finished retrieving data"
    print "vocab size:", len(word2idx), "number of sentences:", len(sentences)
    rnn = RNN(30, [30], len(word2idx))
    rnn.fit(sentences, learning_rate=10e-6, epochs=10, show_fig=True, activation=T.nnet.relu)

    np.save(we_file, rnn.We.get_value())
    with open(w2i_file, 'w') as f:
        json.dump(word2idx, f)

def generate_wikipedia():
    pass

def find_analogies(w1, w2, w3, we_file='word_embeddings.npy', w2i_file='wikipedia_word2idx.json'):
    We = np.load(we_file)
    with open(w2i_file) as f:
        word2idx = json.load(f)

    king = We[word2idx[w1]]
    man = We[word2idx[w2]]
    woman = We[word2idx[w3]]
    v0 = king - man + woman

    def dist1(a, b):
        return np.linalg.norm(a - b)
    def dist2(a, b):
        return 1 - a.dot(b) / (np.linalg.norm(a) * np.linalg.norm(b))

    for dist, name in [(dist1, 'Euclidean'), (dist2, 'cosine')]:
        min_dist = float('inf')
        best_word = '';
        for word, idx in word2idx.iteritems():
            if word not in (w1, w2, w3):
                v1 = We[idx]
                d = dist(v0, v1)
                if d < min_dist:
                    min_dist = d
                    best_word = word
        print "closest match by", name, "distance:", best_word
        print w1, "-", w2, "=", best_word, "-", w3

if __name__ == '__main__':
    train_wikipedia()
    find_analogies('king', 'man', 'woman')
    find_analogies('france', 'paris', 'london')
    find_analogies('france', 'paris', 'rome')
    find_analogies('paris', 'france', 'italy')




