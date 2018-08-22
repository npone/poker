import numpy as np
import pokerClass
import display

a = np.array([[1,1,2,2,3,3,1],[4,4,4,5,3,3,7]]) 

display.ShowCards( pokerClass.ArrayToCards( a ) )
display.ShowScore( pokerClass.ScoreHand( pokerClass.ArrayToCards( a ) ) )








