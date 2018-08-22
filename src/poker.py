
# a test program for calculating chances in poker games
import numpy as np
import pokerClass

print("hello\n")

t = pokerClass.Table( 5 )
t.Hole()
t.ShowTable()
t.ShowPlayers()



t.Flop()
print('Flop:')
t.ShowTable()

t.Turn()
print('Turn:')
t.ShowTable()

t.River()
print('River:')
t.ShowTable()

t.Score()

