import duckdb
con = duckdb.connect()
try:
    result = con.execute("SELECT jaro_winkler_similarity('hello', 'helo')").fetchone()
    print('Available:', result)
except Exception as e:
    print('Not available:', e)