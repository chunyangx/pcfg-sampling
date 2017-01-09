from earley import Earley
from nederhof import Nederhof

from wfsa import WDFSA, make_linear_fsa
from symbol import make_nonterminal, make_terminal

from reader import load_grammar

def test_final_weights():
  # Load the grammar 
  grammar = "/home/cxiao/pcfg_sampling/examples/cfg"
  grammarfmt = "bar"
  wcfg = load_grammar(grammar, grammarfmt, transform=float)
  # Construct the wdfsa
  sentence = "the dog barks"
  wfsa = make_linear_fsa(sentence)
  # Intersection
  parser1 = Earley(wcfg, wfsa)
  forest1 = parser1.do('[S]','[GOAL]')
  parser2 = Nederhof(wcfg, wfsa)
  forest2 = parser2.do('[S]','[GOAL]')
  if forest1.get('[GOAL]')[0].log_prob == forest2.get('[GOAL]')[0].log_prob == 0.0:
    print "Succeed, default final weight is 0.0 in log semiring"
  wfsa.make_final(len(sentence.split()),-0.5)
  parser1 = Earley(wcfg, wfsa)
  forest1 = parser1.do('[S]','[GOAL]')
  parser2 = Nederhof(wcfg, wfsa)
  forest2 = parser2.do('[S]','[GOAL]')
  if forest1.get('[GOAL]')[0].log_prob == forest2.get('[GOAL]')[0].log_prob == -0.5:
    print "Succeed, change final weight to -0.5 in log semiring"

def test_intersection_weights():
  # Load the grammar 
  grammar = "/home/cxiao/pcfg_sampling/examples/cfg"
  grammarfmt = "bar"
  wcfg = load_grammar(grammar, grammarfmt, transform=float)
  # Construct the wdfsa
  wfsa = WDFSA()
  for word in wcfg.terminals:
    wfsa.add_arc(0,0,make_terminal(word),0.0)
  wfsa.add_arc(0,0,make_terminal('dog'),-0.5)
  wfsa.make_initial(0)
  wfsa.make_final(0)
  # Intersection
  parser1 = Earley(wcfg, wfsa)
  forest1 = parser1.do('[S]', '[GOAL]')
  if forest.get('[NN,0-0]')[1].log_prob == -1.7039:
    print "Succeed, the earley intersection correctly changes the weight for a unigram automata"
if __name__ == "__main__":
  test_final_weights()
  test_intersection_weights()
