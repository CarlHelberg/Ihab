
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                );


                CREATE TABLE incomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    frequency TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    FOREIGN KEY (budget_id) REFERENCES budgets (id)
                );

                CREATE TABLE budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
                
                CREATE TABLE categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    budget_amount REAL DEFAULT 0,
                    FOREIGN KEY (budget_id) REFERENCES budgets (id)
                );
                
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    payee TEXT NOT NULL,
                    category_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    memo TEXT,
                    FOREIGN KEY (budget_id) REFERENCES budgets (id),
                    FOREIGN KEY (category_id) REFERENCES categories (id)
                );
            