
# the poker class
import numpy as np
import random
import math
import itertools
import display

class Card:
    def __init__(self, suit=0, num=0):
        self.suit = suit    # suits: 1:Hearts, 2:Diamonds, 3:Spades, 4:Clubs
        self.num = num      # numbers: 1:A, 2:2, ... 13:K


class Deck:
    def __init__(self):
        self.rcd = np.empty( [ 4 , 13 ] , dtype=bool )
        self.rcd.fill( True )   # full deck

    def CountCards( self ):
        ( s , n ) = np.where( self.rcd )
        return len( s )

    def Deal( self ):
        ( s , n ) = np.where( self.rcd )
        randcard = math.floor( random.random() * len(s) )

        self.rcd[ s[ randcard ] , n[ randcard ] ] = False
        return Card( s[ randcard ] + 1 , n[ randcard ] + 1 )

    def Shuffle( self ):
        self.rcd.fill( True )
        return

class Player:
    playerCnt = 0

    def __init__( self , seat, ch ):
        self.hand = []
        self.IsIn = True
        self.chips = ch
        self.seat = seat
        self.score = (0, 0)
        Player.playerCnt += 1

    def Receive( self , c ):
        self.hand.append( c )
        return

    def Bet( self , ch ):
        self.chips = self.chips - ch
        return ch


class Table:
    STARTCHIPS = 100000
    def __init__( self , num ):
        self.pot = 0
        self.numPlayers = num
        self.cards = [] 
        self.deck = Deck()
        self.players = [ Player( i, Table.STARTCHIPS ) for i in range( self.numPlayers ) ]
        self.dealer = 0

    def Next( self ):
        self.deck.shuffle()
        self.cards = []    
        dealer =  0 if self.dealer == self.numPlayers - 1 else self.dealer + 1
        ##### TODO: add sending pot to winner

    def AddPlayer( self ):
        self.players.append( Player( Player.playerCnt, Table.STARTCHIPS ) )
        return

    def AddPlayers( self ):
        for _ in itertools.repeat( None , self.numPlayers ):
            self.AddPlayer()
        return

    def Hole( self ):
        for _ in itertools.repeat( None , 2 ):
            for i in range( self.numPlayers ):
                if self.players[i].IsIn:
                    self.players[ i ].Receive( self.deck.Deal() )
        return

    def Flop( self ):
        for _ in itertools.repeat( None , 3 ):
            self.cards.append( self.deck.Deal() )
        return

    def Turn( self ):
        self.cards.append( self.deck.Deal() )
        return
    
    def River( self ):
        self.cards.append( self.deck.Deal() )
        return

    def Score( self ):
        for p in self.players:
            if p.IsIn:
                p.score = ScoreHand( p.hand + self.cards )
            print( 'Player ' + str(p.seat) + ':' )
            display.ShowScore( p.score )
        

    def ShowTable( self ):
        DisplayCards( self.cards )
        print( ' ' )
        return
    
    def ShowPlayers( self ):
        for p in self.players:
            print( 'Player: ' + str( p.seat ) + ':' )
            DisplayCards(p.hand)
            print( ' ' )
        return



###################
# Game functions: #
###################

# check hand for special combinations:
def CheckFlush( ca ):
    suits = ca[ 0 , : ]
    nums = ca[ 1 , : ]
    for i in range( 1 , 5 ):        # suits are encoded 1..4 (1:Hearts .. 4:Clubs)
        suited = np.where( suits == i )[ 0 ]
        if len( suited ) >= 5:      # Flush found
            key = np.amax( nums[ suited ] )
            return True, key
    return False, None              # not found

def StraightHigh( ranks ):
    # Highest card of a 5-in-a-row straight within `ranks` (values 1..13), counting the
    # Ace (1) as BOTH high (14, for Broadway 10-J-Q-K-A) and low (for the wheel A-2-3-4-5).
    # Returns the high-card rank (14 for Broadway, 5 for the wheel), or None if no straight.
    present = set( int( r ) for r in ranks )
    if 1 in present:
        present.add( 14 )       # Ace also plays high
    for high in range( 14 , 4 , -1 ):           # prefer the best straight
        if all( ( high - offset ) in present for offset in range( 5 ) ):
            return high
    return None

def CheckStraight( ca ):
    high = StraightHigh( ca[ 1 , : ] )
    return ( True, high ) if high is not None else ( False, None )

def CheckStraightFlush( ca ):
    # A straight FLUSH needs five in a row WITHIN A SINGLE SUIT — checking a flush and a
    # straight independently gives false positives (a flush plus an unrelated straight).
    suits = ca[ 0 , : ]
    nums = ca[ 1 , : ]
    best = None
    for i in range( 1 , 5 ):
        suited = nums[ np.where( suits == i )[ 0 ] ]
        if len( suited ) >= 5:
            high = StraightHigh( suited )
            if high is not None and ( best is None or high > best ):
                best = high
    return ( True, best ) if best is not None else ( False, None )

def CheckMultiples( ca ):    # cards is a 2xN array (N=7), row 0: suits, row1: numbers
    suits = ca[ 0 , : ]
    nums = ca[ 1 , : ]
    found = np.array([ False ] * len( nums ))
    groups = np.array([ 0 ] * len( nums ))
    for i in range( len(nums) ):
        if not found[ i ]:
            groups[ i ] += 1
            for j in range( i + 1 , len( nums ) ):
                if nums[ i ] == nums[ j ]:
                    groups[ i ] += 1
                    found[ j ] = True
    QuadKey = None
    TripleKey1 = None
    TripleKey2 = None
    PairKey1 = None
    PairKey2 = None
    PairKey3 = None
    
    f = np.where(groups == 4)[0]
    if len(f):      QuadKey = nums[ f[0] ]
    else:           QuadKey = None
    
    f = np.where(groups == 3)[0]
    if len(f):
        fn =np.flip( np.sort(nums[f]) , axis=0)
        TripleKey1 = fn[0]
        try:        TripleKey2 = fn[1]
        except:     TripleKey2 = None
    
    f = np.where(groups == 2)[0]
    if len(f):
        fn = np.flip( np.sort(nums[f]) , axis=0)
        PairKey1 = fn[0]
        if len(fn) > 1: PairKey2 = fn[1]
        else:           PairKey2 = None
        if len(fn) > 2: PairKey3 = fn[2]
        else:           PairKey3 = None
        
 
    # return: (QuadKey, TripleKey1, TripleKey2, PairKey1, PairKey2, PairKey3)
    return QuadKey, TripleKey1, TripleKey2, PairKey1, PairKey2, PairKey3


def CheckFour(QuadKey):
    if QuadKey:
        return True, QuadKey
    else:
        return False, None

def CheckTriple(TripleKey1):
    if TripleKey1:
        return True, TripleKey1
    else:
        return False, None

def CheckFullHouse(TripleKey1, TripleKey2, PairKey1):
    if TripleKey1:
        if TripleKey2:
            return True, TripleKey1, TripleKey2
        elif PairKey1:
            return True, TripleKey1, PairKey1
        else:
            return False, None, None
    else:
        return False, None, None

def CheckTwoPairs(PairKey1, PairKey2, PairKey3):
    if PairKey1:
        if PairKey2:
            return True, PairKey1, PairKey2
        else:
            return False, None, None
    else:
        return False, None, None
    
def CheckPair(PairKey1):
    if PairKey1:
        return True, PairKey1
    else:
        return False, None


# score hand
def ScoreHand( cards ):
    # Scores:
        # 9: Royal Flush
        # 8: Straight Flush
        # 7: Four of a Kind
        # 6: Full house
        # 5: Flush
        # 4: Straight
        # 3: Three of a Kind
        # 2: Two Pairs
        # 1: Pair
        # 0: High Card
    c = CardsToArray( cards )

    res_sf = CheckStraightFlush(c)
    if res_sf[0]:
        return ( 9 if res_sf[1] == 14 else 8 ), res_sf[1]   # Royal / Straight Flush

    res_flsh = CheckFlush(c)
    res_strt = CheckStraight(c)

    (QuadKey, TripleKey1, TripleKey2, PairKey1, PairKey2, PairKey3) = CheckMultiples(c)
    
    res_4 = CheckFour(QuadKey)
    if res_4[0]:    return 7, res_4[1]              # Four of a Kind
    
    res_32 = CheckFullHouse(TripleKey1, TripleKey2, PairKey1)
    if res_32[0]:   return 6, res_32[1]             # Full House
    
    if res_flsh[0]: return 5, res_flsh[1]           # Flush
    
    if res_strt[0]: return 4, res_strt[1]           # Straight

    res_3 = CheckTriple(TripleKey1)
    if res_3[0]:    return 3, res_3[1]              # Triple
    
    res_22 = CheckTwoPairs(PairKey1, PairKey2, PairKey3)
    if res_22[0]:   return 2, res_22[1], res_22[2]  # Two Pairs
    
    res_2 = CheckPair(PairKey1)
    if res_2[0]:    return 1, res_2[1]              # Pair

    return 0, np.amax(c[1, :])                      # High Card

# utility functions for displaying cards:
suits = { 1:'Hearts' , 2:'Diamonds' , 3:'Spades' , 4:'Clubs' }
def DisplayCards( c ):
  #  print( str( c.num ) + ' of ' + suits[c.suit] )
  #  return
    display.ShowCards( c )
    return


def CardsToArray( cards ):
    arr = np.empty( [ 2 , len( cards ) ] )
    for i in range( len(cards) ):
        arr[ : , i ] = np.array( [ cards[i].suit , cards[i].num ] )
    return arr 


def ArrayToCards( ca ):
    sz = len( ca[0, :] )
    cards = []
    for i in range( sz ):
        cards.append( Card(ca[0, i], ca[1, i]) )
    return cards 
