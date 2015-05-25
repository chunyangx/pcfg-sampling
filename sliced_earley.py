"""
@author wilkeraziz
@author Iason

This work is based on the work of wilkeraziz: earley.py
And extended with Slice Sampling by Iason
"""

from item import ItemFactory
from agenda import Agenda
from collections import defaultdict
from symbol import is_terminal, make_symbol, is_nonterminal
from rule import Rule
from wcfg import WCFG
import collections
from itertools import ifilter
from slice_variable import SliceVariable


class SlicedEarley(object):

    def __init__(self, wcfg, wfsa, slice_variables, conditions, a=0.1, b=1):
        """
        @param wcfg: is the set or rules
        @type RuleSet
        @param fsaId2Symbol: a dictionary that maps fsa ids in terminal symbols of the wcfg
        @param log: whether or not output log information
        """

        self._wcfg = wcfg
        self._wfsa = wfsa

        self._ifactory = ItemFactory()
        self._agenda = Agenda(self._ifactory)
        self._prediction_status = defaultdict(None)

        self.slice_variables = slice_variables
        self.conditions = conditions
        self.a = a
        self.b = b

    def _initialize(self):
        pass

    def do(self, root='[S]', goal='[GOAL]'):

        wfsa = self._wfsa
        wcfg = self._wcfg

        self._initialize()
        agenda = self._agenda

        # start items of the kind
        # GOAL -> * ROOT, where * is an initial state of the wfsa
        [self.axioms(root, start) for start in wfsa.initial_states]
        new_roots = set()

        it = 0
        while agenda:
            it += 1
            item = agenda.pop()

            if item.is_complete():
                status = self.complete_others(item)

                slice_variable = SliceVariable(item, self.slice_variables, self.conditions, self.a, self.b)
                u = slice_variable.get()
                # print "\nUs of ", item.rule, " = ", u

                if item.rule.log_prob > u:
                    # print "\n# Complete: P(", item.rule, ") > Us"
                    # root symbol spanning from a start wfsa state to a final wfsa state
                    # is added as complete regardless the status (since sometimes it won't be able to complete anything else)
                    if item.rule.lhs == root and item.start in wfsa.initial_states and item.dot in wfsa.final_states:
                        agenda.complete(item)
                        new_roots.add((root, item.start, item.dot))
                    elif status >= 0: # any other state is only kept in case it is useful to complete others
                        agenda.complete(item)
                # else:
                    # print "\n DISCARD ITEM", item.rule

            else:

                # this variable is going to indicate the status of the operations performed over the current state
                status = -1 # -1 indicates that nothing could be done

                if is_terminal(item.next):
                    # fire the operation 'scan'
                    status = self.scan(item)
                else:
                    status = self.prediction(item)

                    # if prediction did not result in the creation of active items
                    # because such states have already been created (status == 0)
                    # then we must check whether or not this state is waiting for the completion of some other
                    # that is, we fire 'complete-itself' which attempts to generate active states from the current state
                    # by checking if there is any complete state that could be used to make the current one progress
                    if status == 0:
                        self.complete_itself(item)

                # if the current state has produced active states (status > 0)
                # or it could have produced some if they had not yet been produced (status == 0)
                # we make it passive
                if status >= 0:
                    agenda.make_passive(item)
                # notice that otherwise (status == -1) we discard the state
                # discarding means that it has been popped from the active list
                # but it won't be added to the passive one
                # this should happen only with unreachable states

        # the intersected grammar
        return self.get_cfg(root, goal)

    def axioms(self, symbol, start):
        rules = self._wcfg[symbol]
        if not rules:
            self._prediction_status[(start, symbol)] = False
            return -1

        new_items = [self._ifactory.get_item(rule, start) for rule in rules]
        useful = len(new_items) > 0 # whether or not there are any candidates to become active
        added = self._agenda.extend(new_items) # how many were successfully made active
        self._prediction_status[(start, symbol)] = True
        return added

    def prediction(self, item):
        """
        This operation creates new active states by matching the next symbol (if nonterminal) of a given state to LHS symbols in the grammar.
        @returns whether or not the input state has produced active states, this may be used to decide whether or not the input state must be made passive
        @return -1 if the state is no good for predictions
         0 if the state is good for prediction, but all predicted states already existed
         1 if other states were successfully predicted
        """
        dot = item.dot
        symbol = item.next
        useful = self._prediction_status.get((dot, symbol), None)
        status = 0
        if useful is None:
            rules = self._wcfg[symbol]
            if not rules:
                self._prediction_status[(dot, symbol)] = False
                return -1
            new_items = [self._ifactory.get_item(rule, dot) for rule in rules]
            useful = len(new_items) > 0 # whether or not there are any candidates to become active
            added = self._agenda.extend(new_items) # how many were successfully made active
            self._prediction_status[(dot, symbol)] = True
            return added
        elif useful:
            return 0
        else:
            return -1

    def scan(self, item):
        """
        This operation creates new active states by scanning over the next symbol (if terminal) of a given state.
        @returns -1 if this state is no good for scan
            0 if this state is good for scan, but all scanned states had been produced before
            1 if this state was successfully scanned
        """
        states = [item.dot]
        weights = []
        failed = False
        for sym in item.nextsymbols():
            if is_terminal(sym):
                sto, w = self._wfsa.destination_and_weight(sfrom=states[-1], symbol=sym)
                if sto is not None:
                    states.append(sto)
                    weights.append(w)
                else:
                    failed = True
                    break
            else:
                break
        if failed:
            return -1
        else:
            rule = Rule(item.rule.lhs, item.rule.rhs, item.rule.log_prob + sum(weights))
            new = self._ifactory.get_item(rule, states[-1], item.inner + tuple(states[:-1]))
            status = self._agenda.extend([new])
            return status

    def complete_others(self, item):
        """
        This operation creates new active states from passive states by moving forward a dot over a nonterminal symbol
        if and only if that dot and symbol match those of a given state.
        @returns -1 if can't complete any other
            0 if it could complete, but the resulting states had been produced before
            >1 if it did complete one or more states
        """
        assert item.is_complete(), 'Complete (others) can only handle complete states.'
        incompletes = self._agenda.match_items_waiting_completion(item)
        new_items = [self._ifactory.get_item(incomplete.rule, item.dot, incomplete.inner + (incomplete.dot,)) for incomplete in incompletes]
        if len(new_items) == 0:
            return -1
        else:
            return self._agenda.extend(new_items)

    def complete_itself(self, item):
        """
        This operation creates new active states from passive states by moving forward a dot over a nonterminal symbol
        if and only if that dot and symbol match those of a given state.
        @returns -1 if the input state can't progress (doesn't mean it is a useless state)
            0 if it could progress, but the candidate state was already seen
            1 if it progressed
        """
        destinations = frozenset(complete.dot for complete in self._agenda.match_complete_items(item))
        new_items = [self._ifactory.get_item(item.rule, destination, item.inner + (item.dot,)) for destination in destinations]
        if len(new_items) == 0:
            return -1
        else:
            return self._agenda.extend(new_items)

    def getScannedState(self, item, sto, w):
        h = ConfigHandler.makeWFSATransitionFeatures(w)
        rule = self._rfactory.getRule(item.rule.lhs, item.rule.rhs, elementwisesum(item.features_, h))
        return self._ifactory.getItem(rule, sto, item.inner_ + array('B', [item.dot_]))

    def get_intersected_rule(self, item):
        lhs = make_symbol(item.rule.lhs, item.start, item.dot)
        positions = item.inner + (item.dot,)
        rhs = [make_symbol(sym, positions[i], positions[i + 1]) for i, sym in enumerate(item.rule.rhs)]
        return Rule(lhs, rhs, item.rule.log_prob)

    def get_cfg(self, root, goal):
        """This version is non-recursive (it uses a deque)."""
        G = WCFG()
        G_TEMP = WCFG()

        queuing = set()  # output symbols queuing (or that have already left the queue)
        Q = collections.deque()  # queue of LHS annotated symbols whose rules are to be created

        # organise complete items by annotated lhs symbols
        complete = defaultdict(list)

        # check if there is a root to begin with
        check_root = False

        for item in self._agenda.itercomplete():
            complete[(item.rule.lhs, item.start, item.dot)].append(item)
            if item.rule.lhs == root:
                check_root = True

        # if there is no root, return []
        if check_root is False:
            return []

        # initial and final fsa states of the sentence
        initial_state = next(iter(self._agenda.itergenerating(root)))[0]
        final_state = next(iter(next(iter(self._agenda.itergenerating(root)))[1]))

        # check for each 'root-rule' if there is a valid parse
        for item in complete.get((root, initial_state, final_state), []):
            G_TEMP.add(self.get_intersected_rule(item))
            fsa_states = item.inner + (item.dot,)

            # add the non-terminals of the RHS of the root-node to Q
            for i, sym in ifilter(lambda (_, s): is_nonterminal(s), enumerate(item.rule.rhs)):
                Q.append((sym, fsa_states[i], fsa_states[i + 1]))

            # create rules for symbols which are reachable from other generating symbols (starting from the root ones)
            while Q:
                (lhs, start, end) = Q.pop()

                #  if an item doesn't have complete items, it means that they were truncated!
                if len(complete.get((lhs, start, end), [])) > 0:
                    for item in complete.get((lhs, start, end), []):
                        rule = self.get_intersected_rule(item)
                        G_TEMP.add(rule)
                        fsa_states = item.inner + (item.dot,)

                        for i, sym in ifilter(lambda (_, s): is_nonterminal(s), enumerate(item.rule.rhs)):
                            if (sym, fsa_states[i], fsa_states[i + 1]) not in queuing:  # make sure the same symbol never queues more than once
                                Q.append((sym, fsa_states[i], fsa_states[i + 1]))
                                queuing.add((sym, fsa_states[i], fsa_states[i + 1]))
                else:
                    # reset queuing and TEMP_G, because the parse is broken
                    queuing = set()
                    G_TEMP = WCFG()
                    break

            # the parse is valid, add all rules to G
            for temp_rules in G_TEMP:
                G.add(temp_rules)

            # reset G_TEMP, for potential succeeding parses
            G_TEMP = WCFG()

        # whenever a parse is not empty, add the GOAL node to G.
        if G:
            G.add(Rule(goal, [make_symbol(root, initial_state, final_state)], 0.0))

        return G