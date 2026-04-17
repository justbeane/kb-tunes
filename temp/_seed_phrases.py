"""One-off seed; run then delete."""
import sqlite3

import app

# Unicode escapes keep the file ASCII-safe; DB stores full UTF-8 strings.
PHRASES = [
    "Fiddle me this...",
    "I'm the reel deal.",
    "The jig is up.",
    "Britches get stiches.",
    "Why was the sheep on the boat?",
    "Getting jiggy wit' it.",
    "You'll polka your eye out.",
    "Slide right in.",
    "Keeping it reel.",
    "I study string theory.",
    "Don't step on the craic.",
    "No need to fret.",
    "Time to reel it in.",
    "Don't be so corny, Drew.",
    "Just humour me...",
    "Do you know the Humours of Pusheen?",
    "DTFiddle.",
    "The boys of Bally-BFE.",
    "Interested in a little fling?",
    "Can't read my polka face.",
    "(\u256f\u00b0\u25a1\u00b0)\u256f\ufe35 s,\u028e\u0287\u0287\u0250\u0500 \u02d9\u0287S",
    "Tamlin? Not in this house!",
    "Fit as a fiddle.",
    "Addicted to the craic.",
    "I play R&B - Reels and Barndances.",
    "It identifies as a fiddle.",
    'Was it "diddly doo diddly", or "diddly diddly doo"?',
    "Horny for hornpipes.",
    "I Connaught believe it!",
    "West coast is best coast. Kerry represent!",
    "Waiter! There a hare in my corn!",
    "I'm fluther'd and bet.",
    "Fiddles get me fliuch.",
    "You layin' pipe?",
    "Have ye's no homes to go to?",
    "That's Frankie Gavin. He just thinks he's God.",
    "Wanna see my F-hole?",
    "Yes, I'm a musician. No further questions, please.",
    "Nero did nothing wrong.",
    "West coast style! Straight outta' Killarney",
    "Play Danny Boy!",
    "What would you do if the kettle boiled over?",
    "P\u00f3g mo th\u00f3in.",
    "The ganger got our praties!",
    "I could fancy a pratie.",
    "I try to explain, but I only Kafoozalum.",
    "They don't do it like that in Clare...",
    "Live, laugh, lilt.",
    "Justice for the wee drummer!",
    "Have you heard about the big strong man?",
]


def main() -> None:
    conn = sqlite3.connect(app.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    inserted = 0
    for body in PHRASES:
        b = body.strip()
        if not b:
            continue
        cur.execute("INSERT INTO phrases (body) VALUES (?)", (b,))
        inserted += 1
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM phrases").fetchone()[0]
    conn.close()
    print(f"Inserted {inserted} phrases; table now has {n} row(s) total.")


if __name__ == "__main__":
    main()
