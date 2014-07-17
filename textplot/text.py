

import requests
import re
import textplot.utils as utils
import matplotlib.pyplot as plt
import numpy as np

from nltk.stem import PorterStemmer
from sklearn.neighbors import KernelDensity
from collections import OrderedDict
from scipy import stats


class Text(object):


    @classmethod
    def from_file(cls, path):

        """
        Create a text from a filepath.

        :param cls: The Text class.
        :param path: The filepath.
        """

        return cls(open(path, 'r').read())


    @classmethod
    def from_url(cls, url):

        """
        Create a text from a URL.

        :param cls: The Text class.
        :param path: The URL.
        """

        return cls(requests.get(url).text)


    def __init__(self, text):

        """
        Store and tokenize the text.

        :param text: The text as a raw string.
        """

        self.text = text
        self.stem = PorterStemmer().stem
        self.tokenize()


    def tokenize(self):

        """
        Tokenize the text.
        """

        self.tokens = []
        self.terms = OrderedDict()

        # Strip tags and downcase.
        text = utils.strip_tags(self.text).lower()

        # Walk words in the text.
        pattern = re.compile('[a-z]+')
        for i, match in enumerate(re.finditer(pattern, text)):

            # Stem the token.
            original = match.group(0)
            stemmed = self.stem(original)

            # Token:
            self.tokens.append({
                'original': original,
                'stemmed':  stemmed,
                'left':     match.start(),
                'right':    match.end()
            })

            # Token -> offset:
            if stemmed in self.terms: self.terms[stemmed].append(i)
            else: self.terms[stemmed] = [i]


    @utils.memoize
    def term_counts(self, sort=True):

        """
        Map terms to instance counts.

        :param sort: If true, sort the dictionary by value.
        """

        counts = OrderedDict()
        for term in self.terms:
            counts[term] = len(self.terms[term])

        if sort:
            counts = utils.sort_dict(counts)

        return counts


    @utils.memoize
    def term_counts_log10(self, sort=True):

        """
        Log transform the term counts dictionary.

        :param sort: If true, sort the dictionary by value.
        """

        logs = OrderedDict()
        for term, count in self.term_counts().iteritems():
            logs[term] = np.log10(count)

        if sort:
            logs = utils.sort_dict(logs)

        return logs


    @utils.memoize
    def term_count_zscores(self, sort=True):

        """
        Map terms to instance count zscores.

        :param sort: If true, sort the dictionary by value.
        """

        # Compute zscores for the counts population.
        term_logs = self.term_counts_log10()
        zscores = stats.zscore(term_logs.values())

        # Re-map the terms -> zscores.
        term_zscores = OrderedDict()
        for i, term in enumerate(term_logs):
            term_zscores[term] = zscores[i]

        if sort:
            term_zscores = utils.sort_dict(term_zscores)

        return term_zscores


    @utils.memoize
    def kde(self, term, bandwidth=5000, samples=1000, kernel='epanechnikov'):

        """
        Estimate the kernel density of the instances of term in the text.

        :param term: The term to estimate.
        :param bandwidth: The kernel width.
        :param samples: The number points to sample.
        :param kernel: The kernel function.
        """

        # Term offsets and density sample axis:
        offsets = np.array(self.terms[term])[:, np.newaxis]
        samples = np.linspace(0, len(self.tokens), samples)[:, np.newaxis]

        # Density estimator:
        kde = KernelDensity(kernel=kernel, bandwidth=bandwidth).fit(offsets)

        # Estimate the kernel density.
        return np.exp(kde.score_samples(samples))


    @utils.memoize
    def pair_similarity(self, anchor, sample, **kwargs):

        """
        How similar is the distribution of a sample word to the distribution
        of an anchor word?

        :param anchor: The base term.
        :param sample: The query term.
        """

        a_kde = self.kde(anchor, **kwargs)
        s_kde = self.kde(sample, **kwargs)

        # Get the overlap between the two.
        overlap = [min(a_kde[i], s_kde[i]) for i in xrange(a_kde.size)]
        return np.trapz(overlap)


    @utils.memoize
    def pair_similarities(self, anchor, sort=True, **kwargs):

        """
        Given an anchor word, compute the similarities for all other words.
        Returns an ordered dictionary, with the keys ordered in the same order
        that the terms were originally encountered in the text.

        :param anchor: The anchor word.
        :param sort: If true, sort the dictionary by value.
        """

        anchor = self.stem(anchor)

        sims = OrderedDict()
        for term in self.terms:
            sims[term] = self.pair_similarity(anchor, term, **kwargs)

        if sort:
            sims = utils.sort_dict(sims)

        return sims


    @utils.memoize
    def kde_max(self, term, **kwargs):

        """
        What is the largest value that appears in a word's KDE?

        :param term: The term.
        """

        return self.kde(term, **kwargs).max()


    @utils.memoize
    def kde_maxima(self, sort=True, **kwargs):

        """
        Get the KDE maximum for all terms in the text.

        :param sort: If true, sort the dictionary by value.
        """

        maxima = OrderedDict()
        for term in self.terms:
            maxima[term] = self.kde_max(term, **kwargs)

        if sort:
            maxima = utils.sort_dict(maxima)

        return maxima


    @utils.memoize
    def kde_maxima_zscores(self, sort=True, **kwargs):

        """
        Map terms to KDE maxima zscores.

        :param sort: If true, sort the dictionary by value.
        """

        # Compute zscores for the KDE maxima population.
        kde_maxima = self.kde_maxima(**kwargs)
        zscores = stats.zscore(kde_maxima.values())

        # Re-map the terms -> zscores.
        term_zscores = OrderedDict()
        for i, term in enumerate(kde_maxima):
            term_zscores[term] = zscores[i]

        if sort:
            term_zscores = utils.sort_dict(term_zscores)

        return term_zscores


    @utils.memoize
    def topic_typicalites(self, sort=True, **kwargs):

        """
        "Topic-typical" terms are terms that both:

        (a) Have high KDE maxima, meaning they're unevenly-distributed.
        (b) Occur frequently (not in the long tail of sparse words).

        Compute a statistic for each term in the text that captures this
        combination by adding the zscores for the term's frequency and KDE
        maximum relative to all other terms in the text.

        :param sort: If true, sort the dictionary by value.
        """

        cz = self.term_count_zscores()
        mz = self.kde_maxima_zscores(**kwargs)

        typs = OrderedDict()
        for term in self.terms:
            typs[term] = (cz[term] + mz[term], cz[term], mz[term])

        # TODO|dev
        sort = sorted(typs.iteritems(), key=lambda x: x[1][0], reverse=True)
        return OrderedDict(sort)


    @utils.memoize
    def query(self, query, **kwargs):

        """
        Given a query text as a raw string, sum the kernel density estimates
        of each of the tokens in the query.

        :param query: The query string.
        """

        query_text = Text(query)
        signals = []

        for term in query_text.terms:
            if term in self.terms:
                signals.append(self.kde(term, **kwargs))

        result = np.zeros(signals[0].size)
        for signal in signals: result += signal

        return result


    def plot_term_kdes(self, words, **kwargs):

        """
        Plot kernel density estimates for multiple words.

        :param words: The words to query.
        :param bandwidth: The kernel width.
        """

        for word in words:
            kde = self.kde(self.stem(word), **kwargs)
            plt.plot(kde)

        plt.show()


    def plot_query(self, query, **kwargs):

        """
        Plot a query result.

        :param query: The query string.
        """

        result = self.query(query, **kwargs)
        plt.plot(result)
        plt.show()
