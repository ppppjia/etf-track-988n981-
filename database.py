import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def get_db_path(etf_code):
    """
    根據 ETF 代號（如 00981A、00988A）取得 SQLite 資料庫檔案路徑。
    """
    code = etf_code.upper().replace(".TW", "")
    if "00981" in code or "981" in code:
        db_name = "etf_00981a.db"
    elif "00988" in code or "988" in code:
        db_name = "etf_00988a.db"
    else:
        db_name = f"etf_{code.lower()}.db"
    
    os.makedirs(DB_DIR, exist_ok=True)
    return os.path.join(DB_DIR, db_name)

def get_connection(etf_code):
    """
    取得資料庫連線。
    """
    db_path = get_db_path(etf_code)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(etf_code):
    """
    初始化指定 ETF 的資料庫表綱要。
    """
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    
    # 建立總結資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etf_summary (
            date TEXT PRIMARY KEY,           -- 格式: YYYY-MM-DD
            net_assets REAL,                 -- 淨資產
            units_outstanding REAL,          -- 流通在外單位數
            nav REAL                         -- 每單位淨值 (NAV)
        )
    """)
    
    # 建立持股細目資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etf_holdings (
            date TEXT,                       -- 格式: YYYY-MM-DD
            stock_code TEXT,                 -- 股票代號 (如 2330, AMD US)
            stock_name TEXT,                 -- 股票名稱
            shares INTEGER,                  -- 持股股數
            weight REAL,                     -- 持股權重 (%)
            PRIMARY KEY (date, stock_code)
        )
    """)

    # 建立期貨資料表 (例如台指期貨)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etf_futures (
            date TEXT,                       -- 格式: YYYY-MM-DD
            futures_code TEXT,               -- 期貨代號 (如 TX)
            futures_name TEXT,               -- 期貨名稱
            contracts INTEGER,               -- 期貨口數
            weight REAL,                     -- 權重 (%)
            contract_month TEXT,             -- 合約月份
            PRIMARY KEY (date, futures_code)
        )
    """)
    
    conn.commit()
    conn.close()

def save_etf_data(etf_code, date, summary_data, holdings, futures_list=None):
    """
    儲存 ETF 的總結數據、持股清單與期貨資料。
    """
    init_db(etf_code)
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    
    try:
        # 1. 插入或更新總結資料
        cursor.execute("""
            INSERT OR REPLACE INTO etf_summary (date, net_assets, units_outstanding, nav)
            VALUES (?, ?, ?, ?)
        """, (
            date,
            summary_data.get("net_assets"),
            summary_data.get("units_outstanding"),
            summary_data.get("nav")
        ))
        
        # 2. 插入或更新持股明細
        for holding in holdings:
            cursor.execute("""
                INSERT OR REPLACE INTO etf_holdings (date, stock_code, stock_name, shares, weight)
                VALUES (?, ?, ?, ?, ?)
            """, (
                date,
                holding["stock_code"],
                holding["stock_name"],
                holding["shares"],
                holding["weight"]
            ))

        # 3. 插入或更新期貨資料
        if futures_list:
            for fut in futures_list:
                cursor.execute("""
                    INSERT OR REPLACE INTO etf_futures (date, futures_code, futures_name, contracts, weight, contract_month)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    date,
                    fut["futures_code"],
                    fut["futures_name"],
                    fut["contracts"],
                    fut["weight"],
                    fut["contract_month"]
                ))
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_etf_futures_history(etf_code, futures_code="TX"):
    """
    取得該 ETF 指定期貨的歷史口數與權重變化紀錄，依日期升序排列。
    """
    db_path = get_db_path(etf_code)
    if not os.path.exists(db_path):
        return []
        
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, futures_code, futures_name, contracts, weight, contract_month
        FROM etf_futures
        WHERE futures_code = ?
        ORDER BY date ASC
    """, (futures_code,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_latest_date(etf_code):
    """
    取得該 ETF 在資料庫中最新的交易日期。
    """
    db_path = get_db_path(etf_code)
    if not os.path.exists(db_path):
        return None
        
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM etf_summary")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_etf_summary(etf_code, date):
    """
    取得指定日期的 ETF 總結數據。
    """
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM etf_summary WHERE date = ?", (date,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_holdings_by_date(etf_code, date):
    """
    取得指定日期的所有持股，按權重由高到低排序。
    """
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT stock_code, stock_name, shares, weight 
        FROM etf_holdings 
        WHERE date = ? 
        ORDER BY weight DESC
    """, (date,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_stock_holding_history(etf_code, stock_code):
    """
    取得某隻個股在該 ETF 中的歷史持股與進出變化。
    """
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, shares, weight
        FROM etf_holdings
        WHERE stock_code = ?
        ORDER BY date ASC
    """, (stock_code,))
    rows = cursor.fetchall()
    
    cursor.execute("SELECT date FROM etf_summary ORDER BY date ASC")
    all_dates = [r[0] for r in cursor.fetchall()]
    conn.close()
    
    holdings_by_date = {r["date"]: dict(r) for r in rows}
    
    history = []
    prev_shares = 0
    
    for date in all_dates:
        curr_record = holdings_by_date.get(date)
        if curr_record:
            curr_shares = curr_record["shares"]
            curr_weight = curr_record["weight"]
            change = curr_shares - prev_shares
            prev_shares = curr_shares
            history.append({
                "date": date,
                "shares": curr_shares,
                "weight": curr_weight,
                "change": change
            })
        else:
            if prev_shares > 0:
                change = 0 - prev_shares
                prev_shares = 0
                history.append({
                    "date": date,
                    "shares": 0,
                    "weight": 0.0,
                    "change": change
                })
                
    return history

def get_all_dates(etf_code):
    """
    取得該 ETF 在資料庫中所有有記錄的交易日期，依日期升序排列。
    """
    db_path = get_db_path(etf_code)
    if not os.path.exists(db_path):
        return []
        
    conn = get_connection(etf_code)
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM etf_summary ORDER BY date ASC")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]
