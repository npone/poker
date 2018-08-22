import pokerClass
import numpy as np

def ShowCard(c):
    n = c.num
    s = c.suit
    arr = np.array([['/','-','-','-','-','-','-','-','-','\\',' ',' '],\
                    ['|',' ',' ',' ',' ',' ',' ',' ',' ','|',' ',' '],\
                    ['|',' ',' ',' ',' ',' ',' ',' ',' ','|',' ',' '],\
                    ['|',' ',' ',' ',' ',' ',' ',' ',' ','|',' ',' '],\
                    ['|',' ',' ',' ',' ',' ',' ',' ',' ','|',' ',' '],\
                    ['|',' ',' ',' ',' ',' ',' ',' ',' ','|',' ',' '],\
                    ['\\','-','-','-','-','-','-','-','-','/',' ',' ']])

    if n == 1:    arr[1, 2] = 'A'
    elif n < 10:  arr[1, 2] = str(n)
    elif n == 10: arr[1, 2] = str(1); arr[1, 3] = str(0)
    elif n == 11: arr[1, 2] = 'J'
    elif n == 12: arr[1, 2] = 'Q'
    elif n == 13: arr[1, 2] = 'K'

    diamond = np.array([[' ',' ',' ',' ',' '],\
                        [' ','/','\\',' ',' '],\
                        [' ','\\','/',' ',' '],\
                        [' ',' ',' ',' ',' ']])

    club = np.array([[' ',' ','0',' ',' '],\
                     [' ','0',' ','0',' '],\
                     [' ',' ','A',' ',' '],\
                     [' ',' ',' ',' ',' ']])

    heart = np.array([[' ','/','v','\\',' '],\
                      [' ','\\',' ','/',' '],\
                      [' ',' ','v',' ',' '],\
                      [' ',' ',' ',' ',' ']])

    spade = np.array([[' ',' ','^',' ',' '],\
                      [' ','(','_',')',' '],\
                      [' ',' ','A',' ',' '],\
                      [' ',' ',' ',' ',' ']])

    if s == 1:
        arr[2:6,3:8] = heart
    elif s == 2:
        arr[2:6,3:8] = diamond
    elif s == 3:
        arr[2:6,3:8] = spade
    elif s == 4:
        arr[2:6,3:8] = club

    return arr


def ShowCards( cards ):
    arr = np.empty((7,0))
    for c in cards:
        arr = np.concatenate( ( arr, ShowCard( c ) ), axis=1)
    for ln in arr: print( ''.join(ln) )
    print('\n\n')


# functions to show scores:
RankStrs = {
    9 : 'Royal Flush',
    8 : 'Straight Flush',
    7 : 'Four of a Kind',
    6 : 'Full House',
    5 : 'Flush',
    4 : 'Straight',
    3 : 'Set',
    2 : 'Two Pairs',
    1 : 'Pair',
    0 : 'High Card'
}


def NumToStr( n ):
    if n == 1:  return 'A'
    if n == 11: return 'J'
    if n == 12: return 'Q'
    if n == 13: return 'K'
    return str( n )

def ShowScore( score ):
    sa = score[ 0 ] # Score
    sk1 = score[ 1 ] # Key
    if len(score) > 2: sk2 = score[ 2 ]
    ss = RankStrs[sa]
    if sa in [7, 4, 3, 2, 1, 0]:
        ss += ( ': ' + NumToStr( int(sk1) ) )
        if len(score) > 2:
            ss += ( ', ' + NumToStr( int(2) ) )
            
    print( ss )
    print( ' ' )
