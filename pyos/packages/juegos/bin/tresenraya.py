# tresenraya — contra el ordenador (minimax: no pierde nunca)
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def winner(b):
    for a, c, d in LINES:
        if b[a] != " " and b[a] == b[c] == b[d]:
            return b[a]
    return "=" if " " not in b else None


def minimax(b, turn):
    w = winner(b)
    if w == "O":
        return 1, None
    if w == "X":
        return -1, None
    if w == "=":
        return 0, None
    best = None
    for i in range(9):
        if b[i] == " ":
            b[i] = turn
            score = minimax(b, "X" if turn == "O" else "O")[0]
            b[i] = " "
            if best is None or (turn == "O" and score > best[0]) or (turn == "X" and score < best[0]):
                best = (score, i)
    return best


def show(b):
    for r in range(3):
        print(" " + " | ".join(b[r * 3 + c] if b[r * 3 + c] != " " else str(r * 3 + c + 1) for c in range(3)))
        if r < 2:
            print("---+---+---")


def main(argv):
    b = [" "] * 9
    print("Tú eres X. Elige casilla 1-9.")
    while winner(b) is None:
        show(b)
        s = input("> ")
        if not s:
            return 1
        if not s.isdigit() or not 1 <= int(s) <= 9 or b[int(s) - 1] != " ":
            print("casilla no válida")
            continue
        b[int(s) - 1] = "X"
        if winner(b) is None:
            b[minimax(b, "O")[1]] = "O"
    show(b)
    w = winner(b)
    print({"X": "¡Has ganado!", "O": "Gana el ordenador.", "=": "Empate."}[w])
