# =============================================================================
# Games Router - TaxiDash Madrid
# Matchmaking and multiplayer games: Battleship, Tic-tac-toe, Hangman
# =============================================================================

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import Dict, List, Optional, Set
import asyncio
import json
import random
import string
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/games", tags=["games"])

# =============================================================================
# DATA STRUCTURES
# =============================================================================

# Matchmaking queues by game type
matchmaking_queues: Dict[str, List[dict]] = {
    "battleship": [],
    "tictactoe": [],
    "hangman": []
}

# Active games
active_games: Dict[str, dict] = {}

# WebSocket connections for games
game_connections: Dict[str, Dict[str, WebSocket]] = {}

# Words for hangman (Spanish)
HANGMAN_WORDS = [
    "TAXIMETRO", "LICENCIA", "AEROPUERTO", "TERMINAL", "ESTACION",
    "PASAJERO", "CARRERA", "TARIFA", "MADRID", "CONDUCTOR",
    "ATOCHA", "CHAMARTIN", "BARAJAS", "RECOGIDA", "DESTINO",
    "EQUIPAJE", "PROPINA", "TRAFICO", "SEMAFORO", "ROTONDA",
    "CIBELES", "CASTELLANA", "GRANVIA", "RETIRO", "BERNABEU"
]

# =============================================================================
# MODELS
# =============================================================================

class MatchmakingRequest(BaseModel):
    game_type: str
    user_id: str
    username: str

class GameMove(BaseModel):
    game_id: str
    user_id: str
    move: dict

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_game_id() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def create_battleship_board() -> List[List[str]]:
    """Create empty 10x10 battleship board"""
    return [["~" for _ in range(10)] for _ in range(10)]

def create_tictactoe_board() -> List[List[str]]:
    """Create empty 3x3 tic-tac-toe board"""
    return [["" for _ in range(3)] for _ in range(3)]

def check_tictactoe_winner(board: List[List[str]]) -> Optional[str]:
    """Check if there's a winner in tic-tac-toe"""
    # Check rows
    for row in board:
        if row[0] and row[0] == row[1] == row[2]:
            return row[0]
    # Check columns
    for col in range(3):
        if board[0][col] and board[0][col] == board[1][col] == board[2][col]:
            return board[0][col]
    # Check diagonals
    if board[0][0] and board[0][0] == board[1][1] == board[2][2]:
        return board[0][0]
    if board[0][2] and board[0][2] == board[1][1] == board[2][0]:
        return board[0][2]
    return None

def is_tictactoe_draw(board: List[List[str]]) -> bool:
    """Check if tic-tac-toe is a draw"""
    for row in board:
        for cell in row:
            if not cell:
                return False
    return True

def place_ships_randomly(board: List[List[str]]) -> List[List[str]]:
    """Place ships randomly on battleship board"""
    ships = [5, 4, 3, 3, 2]  # Ship sizes
    
    for ship_size in ships:
        placed = False
        attempts = 0
        while not placed and attempts < 100:
            attempts += 1
            horizontal = random.choice([True, False])
            if horizontal:
                row = random.randint(0, 9)
                col = random.randint(0, 9 - ship_size)
                # Check if space is free
                can_place = all(board[row][col + i] == "~" for i in range(ship_size))
                if can_place:
                    for i in range(ship_size):
                        board[row][col + i] = "S"
                    placed = True
            else:
                row = random.randint(0, 9 - ship_size)
                col = random.randint(0, 9)
                can_place = all(board[row + i][col] == "~" for i in range(ship_size))
                if can_place:
                    for i in range(ship_size):
                        board[row + i][col] = "S"
                    placed = True
    return board

def count_ships(board: List[List[str]]) -> int:
    """Count remaining ships on board"""
    count = 0
    for row in board:
        for cell in row:
            if cell == "S":
                count += 1
    return count

# =============================================================================
# MATCHMAKING ENDPOINTS
# =============================================================================

@router.post("/matchmaking/join")
async def join_matchmaking(request: MatchmakingRequest):
    """Join matchmaking queue for a game"""
    game_type = request.game_type.lower()
    
    if game_type not in matchmaking_queues:
        raise HTTPException(status_code=400, detail="Tipo de juego no válido")
    
    # Check if user is already in queue
    for player in matchmaking_queues[game_type]:
        if player["user_id"] == request.user_id:
            return {"status": "already_queued", "position": matchmaking_queues[game_type].index(player) + 1}
    
    # Add to queue
    player_data = {
        "user_id": request.user_id,
        "username": request.username,
        "joined_at": datetime.utcnow().isoformat()
    }
    matchmaking_queues[game_type].append(player_data)
    
    # Check if we can match players
    if len(matchmaking_queues[game_type]) >= 2:
        # Create a game!
        player1 = matchmaking_queues[game_type].pop(0)
        player2 = matchmaking_queues[game_type].pop(0)
        
        game_id = generate_game_id()
        
        # Initialize game state based on type
        if game_type == "battleship":
            game_state = {
                "type": "battleship",
                "players": {
                    player1["user_id"]: {
                        "username": player1["username"],
                        "board": place_ships_randomly(create_battleship_board()),
                        "opponent_view": create_battleship_board(),
                        "ships_remaining": 17  # 5+4+3+3+2
                    },
                    player2["user_id"]: {
                        "username": player2["username"],
                        "board": place_ships_randomly(create_battleship_board()),
                        "opponent_view": create_battleship_board(),
                        "ships_remaining": 17
                    }
                },
                "current_turn": player1["user_id"],
                "status": "active",
                "winner": None
            }
        elif game_type == "tictactoe":
            game_state = {
                "type": "tictactoe",
                "players": {
                    player1["user_id"]: {"username": player1["username"], "symbol": "X"},
                    player2["user_id"]: {"username": player2["username"], "symbol": "O"}
                },
                "board": create_tictactoe_board(),
                "current_turn": player1["user_id"],
                "status": "active",
                "winner": None
            }
        elif game_type == "hangman":
            word = random.choice(HANGMAN_WORDS)
            # One player chooses word (or random), other guesses
            game_state = {
                "type": "hangman",
                "players": {
                    player1["user_id"]: {"username": player1["username"], "role": "guesser"},
                    player2["user_id"]: {"username": player2["username"], "role": "watcher"}
                },
                "word": word,
                "revealed": ["_" if c != " " else " " for c in word],
                "guessed_letters": [],
                "wrong_guesses": 0,
                "max_wrong": 6,
                "current_turn": player1["user_id"],
                "status": "active",
                "winner": None
            }
        
        game_state["game_id"] = game_id
        game_state["created_at"] = datetime.utcnow().isoformat()
        game_state["player_ids"] = [player1["user_id"], player2["user_id"]]
        
        active_games[game_id] = game_state
        game_connections[game_id] = {}
        
        return {
            "status": "matched",
            "game_id": game_id,
            "opponent": player2["username"] if request.user_id == player1["user_id"] else player1["username"]
        }
    
    return {
        "status": "queued",
        "position": len(matchmaking_queues[game_type]),
        "queue_size": len(matchmaking_queues[game_type])
    }

@router.post("/matchmaking/leave")
async def leave_matchmaking(request: MatchmakingRequest):
    """Leave matchmaking queue"""
    game_type = request.game_type.lower()
    
    if game_type not in matchmaking_queues:
        raise HTTPException(status_code=400, detail="Tipo de juego no válido")
    
    matchmaking_queues[game_type] = [
        p for p in matchmaking_queues[game_type] 
        if p["user_id"] != request.user_id
    ]
    
    return {"status": "left_queue"}

@router.get("/matchmaking/status/{game_type}/{user_id}")
async def matchmaking_status(game_type: str, user_id: str):
    """Check matchmaking status"""
    game_type = game_type.lower()
    
    if game_type not in matchmaking_queues:
        raise HTTPException(status_code=400, detail="Tipo de juego no válido")
    
    # Check if user has been matched to a game
    for game_id, game in active_games.items():
        if user_id in game.get("player_ids", []) and game["status"] == "active":
            opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
            opponent_name = game["players"][opponent_id]["username"]
            return {
                "status": "matched",
                "game_id": game_id,
                "opponent": opponent_name
            }
    
    # Check queue position
    for i, player in enumerate(matchmaking_queues[game_type]):
        if player["user_id"] == user_id:
            return {
                "status": "queued",
                "position": i + 1,
                "queue_size": len(matchmaking_queues[game_type])
            }
    
    return {"status": "not_in_queue"}

@router.get("/queue-counts")
async def get_queue_counts():
    """Get number of players in each queue"""
    return {
        "battleship": len(matchmaking_queues["battleship"]),
        "tictactoe": len(matchmaking_queues["tictactoe"]),
        "hangman": len(matchmaking_queues["hangman"])
    }

# =============================================================================
# GAME STATE ENDPOINTS
# =============================================================================

@router.get("/game/{game_id}")
async def get_game_state(game_id: str, user_id: str):
    """Get current game state (filtered for the requesting user)"""
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="Partida no encontrada")
    
    game = active_games[game_id]
    
    if user_id not in game["player_ids"]:
        raise HTTPException(status_code=403, detail="No eres parte de esta partida")
    
    # Return filtered state based on game type
    if game["type"] == "battleship":
        opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
        return {
            "game_id": game_id,
            "type": game["type"],
            "my_board": game["players"][user_id]["board"],
            "opponent_view": game["players"][user_id]["opponent_view"],
            "my_ships_remaining": game["players"][user_id]["ships_remaining"],
            "opponent_ships_remaining": game["players"][opponent_id]["ships_remaining"],
            "current_turn": game["current_turn"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"]
        }
    elif game["type"] == "tictactoe":
        opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
        return {
            "game_id": game_id,
            "type": game["type"],
            "board": game["board"],
            "my_symbol": game["players"][user_id]["symbol"],
            "current_turn": game["current_turn"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"]
        }
    elif game["type"] == "hangman":
        opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
        return {
            "game_id": game_id,
            "type": game["type"],
            "revealed": game["revealed"],
            "guessed_letters": game["guessed_letters"],
            "wrong_guesses": game["wrong_guesses"],
            "max_wrong": game["max_wrong"],
            "my_role": game["players"][user_id]["role"],
            "current_turn": game["current_turn"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"],
            "word": game["word"] if game["status"] == "finished" else None
        }

@router.post("/game/move")
async def make_move(move: GameMove):
    """Make a move in a game"""
    game_id = move.game_id
    user_id = move.user_id
    
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="Partida no encontrada")
    
    game = active_games[game_id]
    
    if user_id not in game["player_ids"]:
        raise HTTPException(status_code=403, detail="No eres parte de esta partida")
    
    if game["status"] != "active":
        raise HTTPException(status_code=400, detail="La partida ha terminado")
    
    if game["current_turn"] != user_id:
        raise HTTPException(status_code=400, detail="No es tu turno")
    
    opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
    result = {"valid": False, "message": "Movimiento no válido"}
    
    # Process move based on game type
    if game["type"] == "battleship":
        row = move.move.get("row")
        col = move.move.get("col")
        
        if row is None or col is None or not (0 <= row < 10) or not (0 <= col < 10):
            raise HTTPException(status_code=400, detail="Coordenadas inválidas")
        
        opponent_board = game["players"][opponent_id]["board"]
        my_view = game["players"][user_id]["opponent_view"]
        
        if my_view[row][col] != "~":
            raise HTTPException(status_code=400, detail="Ya disparaste a esta casilla")
        
        if opponent_board[row][col] == "S":
            # Hit!
            opponent_board[row][col] = "X"
            my_view[row][col] = "X"
            game["players"][opponent_id]["ships_remaining"] -= 1
            result = {"valid": True, "hit": True, "message": "¡Tocado!"}
            
            # Check if all ships sunk
            if game["players"][opponent_id]["ships_remaining"] <= 0:
                game["status"] = "finished"
                game["winner"] = user_id
                result["game_over"] = True
                result["message"] = "¡Hundido! ¡Has ganado!"
        else:
            # Miss
            opponent_board[row][col] = "O"
            my_view[row][col] = "O"
            result = {"valid": True, "hit": False, "message": "Agua"}
        
        # Switch turn
        game["current_turn"] = opponent_id
        
    elif game["type"] == "tictactoe":
        row = move.move.get("row")
        col = move.move.get("col")
        
        if row is None or col is None or not (0 <= row < 3) or not (0 <= col < 3):
            raise HTTPException(status_code=400, detail="Coordenadas inválidas")
        
        if game["board"][row][col]:
            raise HTTPException(status_code=400, detail="Casilla ocupada")
        
        symbol = game["players"][user_id]["symbol"]
        game["board"][row][col] = symbol
        result = {"valid": True, "message": f"Colocaste {symbol}"}
        
        # Check winner
        winner_symbol = check_tictactoe_winner(game["board"])
        if winner_symbol:
            game["status"] = "finished"
            game["winner"] = user_id
            result["game_over"] = True
            result["message"] = "¡Has ganado!"
        elif is_tictactoe_draw(game["board"]):
            game["status"] = "finished"
            game["winner"] = "draw"
            result["game_over"] = True
            result["message"] = "¡Empate!"
        else:
            # Switch turn
            game["current_turn"] = opponent_id
            
    elif game["type"] == "hangman":
        letter = move.move.get("letter", "").upper()
        
        if not letter or len(letter) != 1 or not letter.isalpha():
            raise HTTPException(status_code=400, detail="Letra inválida")
        
        if letter in game["guessed_letters"]:
            raise HTTPException(status_code=400, detail="Ya adivinaste esa letra")
        
        game["guessed_letters"].append(letter)
        
        if letter in game["word"]:
            # Correct guess - reveal letters
            for i, c in enumerate(game["word"]):
                if c == letter:
                    game["revealed"][i] = letter
            result = {"valid": True, "correct": True, "message": f"¡Correcto! La letra {letter} está en la palabra"}
            
            # Check if word is complete
            if "_" not in game["revealed"]:
                game["status"] = "finished"
                game["winner"] = user_id
                result["game_over"] = True
                result["message"] = f"¡Has ganado! La palabra era: {game['word']}"
        else:
            # Wrong guess
            game["wrong_guesses"] += 1
            result = {"valid": True, "correct": False, "message": f"La letra {letter} no está"}
            
            if game["wrong_guesses"] >= game["max_wrong"]:
                game["status"] = "finished"
                game["winner"] = opponent_id
                result["game_over"] = True
                result["message"] = f"¡Ahorcado! La palabra era: {game['word']}"
    
    # Notify via WebSocket if connected
    await notify_game_update(game_id, game, result)
    
    return result

@router.post("/game/{game_id}/forfeit")
async def forfeit_game(game_id: str, user_id: str):
    """Forfeit a game"""
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="Partida no encontrada")
    
    game = active_games[game_id]
    
    if user_id not in game["player_ids"]:
        raise HTTPException(status_code=403, detail="No eres parte de esta partida")
    
    if game["status"] != "active":
        raise HTTPException(status_code=400, detail="La partida ya terminó")
    
    opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
    game["status"] = "finished"
    game["winner"] = opponent_id
    
    await notify_game_update(game_id, game, {"forfeit": True, "loser": user_id})
    
    return {"status": "forfeited", "winner": opponent_id}

# =============================================================================
# WEBSOCKET FOR REAL-TIME UPDATES
# =============================================================================

@router.websocket("/ws/{game_id}/{user_id}")
async def game_websocket(websocket: WebSocket, game_id: str, user_id: str):
    """WebSocket connection for real-time game updates"""
    await websocket.accept()
    
    if game_id not in active_games:
        await websocket.send_json({"error": "Partida no encontrada"})
        await websocket.close()
        return
    
    game = active_games[game_id]
    
    if user_id not in game["player_ids"]:
        await websocket.send_json({"error": "No eres parte de esta partida"})
        await websocket.close()
        return
    
    # Register connection
    if game_id not in game_connections:
        game_connections[game_id] = {}
    game_connections[game_id][user_id] = websocket
    
    try:
        # Send initial game state
        await websocket.send_json({
            "type": "game_state",
            "data": await get_filtered_game_state(game_id, user_id)
        })
        
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_json()
            
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "move":
                # Process move
                move = GameMove(game_id=game_id, user_id=user_id, move=data.get("move", {}))
                try:
                    result = await make_move(move)
                    await websocket.send_json({"type": "move_result", "data": result})
                except HTTPException as e:
                    await websocket.send_json({"type": "error", "message": e.detail})
                    
    except WebSocketDisconnect:
        if game_id in game_connections and user_id in game_connections[game_id]:
            del game_connections[game_id][user_id]

async def get_filtered_game_state(game_id: str, user_id: str) -> dict:
    """Get game state filtered for a specific user"""
    game = active_games[game_id]
    opponent_id = [pid for pid in game["player_ids"] if pid != user_id][0]
    
    if game["type"] == "battleship":
        return {
            "type": "battleship",
            "my_board": game["players"][user_id]["board"],
            "opponent_view": game["players"][user_id]["opponent_view"],
            "my_ships": game["players"][user_id]["ships_remaining"],
            "opponent_ships": game["players"][opponent_id]["ships_remaining"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"]
        }
    elif game["type"] == "tictactoe":
        return {
            "type": "tictactoe",
            "board": game["board"],
            "my_symbol": game["players"][user_id]["symbol"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"]
        }
    elif game["type"] == "hangman":
        return {
            "type": "hangman",
            "revealed": game["revealed"],
            "guessed_letters": game["guessed_letters"],
            "wrong_guesses": game["wrong_guesses"],
            "max_wrong": game["max_wrong"],
            "is_my_turn": game["current_turn"] == user_id,
            "opponent": game["players"][opponent_id]["username"],
            "status": game["status"],
            "winner": game["winner"],
            "word": game["word"] if game["status"] == "finished" else None
        }

async def notify_game_update(game_id: str, game: dict, result: dict):
    """Notify all players of a game update"""
    if game_id not in game_connections:
        return
    
    for player_id, ws in game_connections[game_id].items():
        try:
            await ws.send_json({
                "type": "game_update",
                "state": await get_filtered_game_state(game_id, player_id),
                "result": result
            })
        except:
            pass
