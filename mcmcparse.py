__author__ = 'Iason'

import argparse
import sys
import logging
import math
from reader import load_grammar
from collections import defaultdict, Counter
from sentence import make_sentence
from slice_variable import SliceVariable
from sliced_earley import SlicedEarley
from sliced_nederhof import SlicedNederhof
from topsort import top_sort
from inference import inside
from generalisedSampling import GeneralisedSampling
from symbol import parse_annotated_nonterminal, make_nonterminal
import time
from scipy.stats import beta


def get_conditions(d):
    """
    update conditions: the probability of each state of the previous derivation is assigned
    to the condition of that state
    """
    return {parse_annotated_nonterminal(rule.lhs): rule.log_prob for rule in d}


def sliced_sampling(wcfg, wfsa, root='[S]', goal='[GOAL]', n_samples=100, n_burn=100, max_iterations=1000, a=[0.1, 0.1], b=[1.0, 1.0], intersection='nederhof'):
    """
    Sample N derivations in maximum K iterations with Slice Sampling
    """
    
    if intersection == 'nederhof':
        logging.info('Using Nederhof parser')
        parser_type = SlicedNederhof
    elif intersection == 'earley':
        parser_type = SlicedEarley
        logging.info('Using Earley parser')
    else:
        raise NotImplementedError('I do not know this algorithm: %s' % intersection)
    
    samples = []
    slice_vars = SliceVariable(a=a[0], b=b[0])
    it = 0
    while len(samples) < n_samples and it < max_iterations:
        it += 1
        if it % 10 == 0:
            logging.info('it=%d samples=%d', it, len(samples))
        
        d = sliced_sample(wcfg, wfsa, root, goal, parser_type(wcfg, wfsa, slice_vars))

        if d is not None:
            if n_burn > 0:  # in case we are burning derivations, we do not add them to the list
                n_burn -= 1  # but we still use them to update the slice variables
            else:
                samples.append(d)

            # because we have a derivation
            # we reset the assignments of the slice variables
            # we fix new conditions
            # and we move on to the second pair of parameters of the beta
            conditions = get_conditions(d)
            slice_vars.reset(conditions, a[1], b[1])
        else:
            # because we do not have a derivation
            # but we are indeed finishing one iteration
            # we reset the assignments of the slice variables
            # however we leave the conditions unchanged
            # similarly, we do not change the parameters of the beta
            slice_vars.reset()

    counts = Counter(tuple(d) for d in samples)
    for d, n in counts.most_common():
        score = sum(r.log_prob for r in d)
        print '# n=%s estimate=%s score=%s' % (n, float(n)/len(samples), score)
        for r in d:
            print r
        print 

    # print "\nCount failed derivations: ", it - sum(samples.values())


def edge_uniform_weight(edge, goal, slicevars):
    """
    Return a uniform view of the edge's log-probability.
    :param edge: an edge
    :param goal: the goal node (gets a special treatment because there are no slice variables for it)
    :param slicevars: a SliceVariable object
    :returns: 1/beta.pdf(u_s; a, b)
    """
    if edge.lhs == goal:
        # rules rooted by the goal symbol have probability 1 (or 0 in log-domain) and there is no slice variable for the goal symbol
        return 0.0
    else:
        sym, start, end = parse_annotated_nonterminal(edge.lhs)
        return slicevars.weight(sym, start, end, edge.log_prob)

def sliced_sample(wcfg, wfsa, root, goal, parser):
    """
    Sample a derivation given a wcfg and a wfsa, with Slice Sampling, a
    form of MCMC-sampling
    """

    logging.debug('Parsing...')
    forest = parser.do(root, goal)

    if not forest:
        logging.debug('NO PARSE FOUND')
        return None

    else:
        logging.debug('Forest: rules=%d', len(forest))
        logging.debug('Topsorting...')

        # sort the forest
        sorted_nodes = top_sort(forest)

        # calculate the inside weight of the sorted forest
        logging.debug('Inside...')
        # here we compute inside weights, however with a new uniform weight function over edges
        inside_prob = inside(forest, sorted_nodes, omega=lambda edge: edge_uniform_weight(edge, goal, parser.slice_vars))

        logging.debug('Sampling...')
        # retrieve a random derivation, with respect to the inside weight distribution
        # again, we sample with respect to a uniform function over edges
        gen_sampling = GeneralisedSampling(forest, inside_prob, omega=lambda edge: edge_uniform_weight(edge, goal, parser.slice_vars))
        d = gen_sampling.sample(goal)

        return d


def main(args):

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)s %(message)s')

    logging.info('Loading grammar...')
    if args.log:
        wcfg = load_grammar(args.grammar, args.grammarfmt, transform=math.log)
    else:
        wcfg = load_grammar(args.grammar, args.grammarfmt, transform=float)

    logging.info(' %d rules', len(wcfg))

    for input_str in args.input:
        sentence, extra_rules = make_sentence(input_str, wcfg.terminals, args.unkmodel, args.default_symbol)
        wcfg.update(extra_rules)

        start = time.time()

        sliced_sampling(wcfg, sentence.fsa,
                        make_nonterminal(args.start),
                        make_nonterminal(args.goal),
                        args.samples, args.burn, args.max,
                        args.a, args.b,
                        args.intersection)

        end = time.time()
        print "DURATION  = ", end - start



def argparser():
    """parse command line arguments"""
    parser = argparse.ArgumentParser(prog='mcmcparse')

    parser.description = 'MCMC Earley parser'
    parser.formatter_class = argparse.ArgumentDefaultsHelpFormatter

    parser.add_argument('grammar',
            type=str,
            help='path to CFG rules (or prefix in case of discodop format)')
    parser.add_argument('input', nargs='?',
            type=argparse.FileType('r'), default=sys.stdin,
            help='input corpus (one sentence per line)')
    parser.add_argument('--intersection',
            type=str, default='nederhof', choices=['nederhof', 'earley'],
            help="intersection algorithm (nederhof: bottom-up; earley: top-down)")
    parser.add_argument('--log',
            action='store_true',
            help='applies the log transform to the probabilities of the rules')
    parser.add_argument('--start',
            type=str, default='S', 
            help="start symbol of the grammar")
    parser.add_argument('--goal',
            type=str, default='GOAL', 
            help="goal symbol for intersection")
    parser.add_argument('--samples',
                        type=int, default=100,
                        help='The number of samples')
    parser.add_argument('--burn',
                        type=int, default=0,
                        help='The number of initial samples to discard')
    parser.add_argument('--max',
                        type=int, default=1000,
                        help='The maximum number of iterations')
    parser.add_argument('-a',
                        type=float, nargs=2, default=[0.1, 0.3], metavar='BEFORE AFTER',
                        help='a, first Beta parameter before and after finding the first derivation')
    parser.add_argument('-b',
                        type=float, nargs=2, default=[1.0, 1.0], metavar='BEFORE AFTER',
                        help='b, second Beta parameter before and after finding the first derivation')
    parser.add_argument('--unkmodel',
            type=str, default=None,
            choices=['passthrough', 'stfdbase', 'stfd4', 'stfd6'],
            help="unknown word model")
    parser.add_argument('--default-symbol',
            type=str, default='X',
            help='default nonterminal (use for pass-through rules)')
    parser.add_argument('--verbose', '-v',
            action='store_true',
            help='increase the verbosity level')
    parser.add_argument('--grammarfmt',
            type=str, default='bar', choices=['bar', 'discodop'],
            help="grammar format ('bar' is the native format)")

    return parser

if __name__ == '__main__':
    main(argparser().parse_args())
