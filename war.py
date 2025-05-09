"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2


def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    received = bytearray()
    while len(received) < numbytes:
        chunk = sock.recv(numbytes - len(received))
        if not chunk:
            raise ConnectionResetError("Socket closed before receiving enough bytes")
        received.extend(chunk)
    return bytes(received)


def kill_game(game):
    """
    TODO: If either client sends a bad message, immediately nuke the game.
    """
    for s in (game.p1, game.p2):
        try:
            s.close()
        except Exception:
            pass


def compare_cards(card1, card2):
    """
    TODO: Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    r1 = (card1 % 13) + 2
    r2 = (card2 % 13) + 2
    if r1 > r2:
        return 1
    elif r1 < r2:
        return -1
    else:
        return 0


def deal_cards():
    """
    TODO: Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))
    random.shuffle(deck)
    return deck[:26], deck[26:]


def serve_game(host, port):
    """
    TODO: Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    
    print(f"WAR server starting on {host}:{port}")
    logging.info("Server init %s:%d", host, port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen()

        while True:
            conn, addr = sock.accept()
            logging.info("Client connected from %s", addr)
            waiting_clients.append(conn)

            if len(waiting_clients) >= 2:
                p1 = waiting_clients.pop(0)
                p2 = waiting_clients.pop(0)

                def handle_game(game):
                    try:
                        for s in (game.p1, game.p2):
                            cmd = readexactly(s, 1)[0]
                            payload = readexactly(s, 1)
                            if cmd != Command.WANTGAME.value or payload != b"\x00":
                                kill_game(game)
                                return
                        hand1, hand2 = deal_cards()
                        game.p1.sendall(bytes([Command.GAMESTART.value]) + bytes(hand1))
                        game.p2.sendall(bytes([Command.GAMESTART.value]) + bytes(hand2))

                        unused1, unused2 = set(hand1), set(hand2)

                        for rnd in range(26):
                            if readexactly(game.p1, 1)[0] != Command.PLAYCARD.value:
                                kill_game(game); return
                            c1 = readexactly(game.p1, 1)[0]

                            if readexactly(game.p2, 1)[0] != Command.PLAYCARD.value:
                                kill_game(game); return
                            c2 = readexactly(game.p2, 1)[0]
                            
                            if (
                                c1 not in unused1 or
                                c2 not in unused2 or
                                not (0 <= c1 < 52 and 0 <= c2 < 52)
                            ):
                                kill_game(game)
                                return
                            unused1.remove(c1)
                            unused2.remove(c2)

                            cmp = compare_cards(c1, c2)
                            logging.debug(
                                "Round %02d | P1 card=%2d , P2 card=%2d → %s",
                                rnd + 1, c1, c2,
                                "P1 win" if cmp > 0 else "P2 win" if cmp < 0 else "draw"
                            )
                            if cmp > 0:
                                r1, r2 = Result.WIN.value, Result.LOSE.value
                            elif cmp < 0:
                                r1, r2 = Result.LOSE.value, Result.WIN.value
                            else:
                                r1 = r2 = Result.DRAW.value
                            
                            game.p1.sendall(bytes([Command.PLAYRESULT.value, r1]))
                            game.p2.sendall(bytes([Command.PLAYRESULT.value, r2]))

                        logging.info("Game complete — closing sockets.")
                    except Exception as e:
                        logging.error("Game error: %s", e)
                    finally:
                        kill_game(game)

                threading.Thread(
                    target=handle_game,
                    args=(Game(p1, p2),),
                    daemon=True
                ).start()



async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)


async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("Connection reset by peer")
        return 0
    except asyncio.exceptions.IncompleteReadError:
        logging.error("Incomplete read (server closed connection)")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    if len(args) < 3:
        print("Usage:")
        print("  Server: python war.py server <host> <port>")
        print("  Client: python war.py client <host> <port>")
        return
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])