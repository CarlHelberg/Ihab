import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, g, flash, session

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['DATABASE'] = 'budget.db'

# Database functions
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def modify_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()

# Routes
@app.route('/')
def index():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Get budgets for this user
    budgets = query_db('SELECT * FROM budgets WHERE user_id = ?', [session['user_id']])
    
    return render_template('dashboard.html', budgets=budgets)

@app.route('/budget/<int:budget_id>')
def view_budget(budget_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Check if this budget belongs to the current user
    budget = query_db('SELECT * FROM budgets WHERE id = ? AND user_id = ?', 
                      [budget_id, session['user_id']], one=True)
    
    if not budget:
        flash('Budget not found')
        return redirect(url_for('index'))
    
    # Get categories for this budget
    categories = query_db('SELECT * FROM categories WHERE budget_id = ?', [budget_id])
    
    # Get transactions for this budget
    transactions = query_db('''
        SELECT t.*, c.name as category_name FROM transactions t
        JOIN categories c ON t.category_id = c.id
        WHERE t.budget_id = ? ORDER BY t.date DESC
    ''', [budget_id])
    
    # Get incomes for this budget
    incomes = query_db('SELECT * FROM incomes WHERE budget_id = ? ORDER BY start_date DESC', [budget_id])

    # Calculate total income per month
    monthly_income = 0
    for income in incomes:
        # Calculate monthly equivalent based on frequency
        if income['frequency'] == 'monthly':
            monthly_income += income['amount']
        elif income['frequency'] == 'bi-weekly':
            monthly_income += (income['amount'] * 26) / 12
        elif income['frequency'] == 'weekly':
            monthly_income += (income['amount'] * 52) / 12
        elif income['frequency'] == 'yearly':
            monthly_income += income['amount'] / 12
        elif income['frequency'] == 'once':
            # For one-time incomes, we don't add to monthly calculation
            pass

    # Calculate category totals
    category_totals = {}
    total_budgeted = 0
    total_spent = 0

    for cat in categories:
        spent = query_db('''
            SELECT SUM(amount) as total FROM transactions
            WHERE category_id = ? AND budget_id = ? AND amount < 0
        ''', [cat['id'], budget_id], one=True)

        allocated = cat['budget_amount']
        total_budgeted += allocated
        category_spent = spent['total'] or 0
        total_spent += abs(category_spent)
        remaining = allocated + category_spent  # category_spent is negative

        category_totals[cat['id']] = {
            'name': cat['name'],
            'allocated': allocated,
            'spent': category_spent,
            'remaining': remaining
        }

    # Calculate total one-time income (transactions with positive amount)
    one_time_income = query_db('''
        SELECT SUM(amount) as total FROM transactions
        WHERE budget_id = ? AND amount > 0
    ''', [budget_id], one=True)

    one_time_income_total = one_time_income['total'] or 0

    # Calculate how much is unallocated
    unallocated = monthly_income - total_budgeted

    # Summary stats
    summary = {
        'monthly_income': monthly_income,
        'one_time_income': one_time_income_total,
        'total_budgeted': total_budgeted,
        'total_spent': total_spent,
        'unallocated': unallocated
    }

    return render_template('budget.html',
                           budget=budget,
                           categories=categories,
                           transactions=transactions,
                           incomes=incomes,
                           category_totals=category_totals,
                           summary=summary)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = query_db('SELECT * FROM users WHERE username = ? AND password = ?',
                        [username, password], one=True)
        
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user_exists = query_db('SELECT * FROM users WHERE username = ?', [username], one=True)
        
        if user_exists:
            flash('Username already exists')
        else:
            modify_db('INSERT INTO users (username, password) VALUES (?, ?)',
                    [username, password])
            flash('Account created, please login')
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/add_budget', methods=['POST'])
def add_budget():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    name = request.form['name']
    
    modify_db('''
        INSERT INTO budgets (user_id, name)
        VALUES (?, ?)
    ''', [session['user_id'], name])
    
    return redirect(url_for('index'))

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    budget_id = request.form['budget_id']
    date = request.form['date']
    payee = request.form['payee']
    category_id = request.form['category_id']
    amount = float(request.form['amount'])
    memo = request.form['memo']
    
    # For expenses, make amount negative
    if 'expense' in request.form and request.form['expense'] == 'on':
        amount = -abs(amount)
    
    modify_db('''
        INSERT INTO transactions (budget_id, date, payee, category_id, amount, memo)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', [budget_id, date, payee, category_id, amount, memo])
    
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/edit_transaction/<int:transaction_id>', methods=['GET', 'POST'])
def edit_transaction(transaction_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Get the transaction
    transaction = query_db('''
        SELECT t.*, b.user_id FROM transactions t
        JOIN budgets b ON t.budget_id = b.id
        WHERE t.id = ?
    ''', [transaction_id], one=True)
    
    # Check if transaction exists and belongs to the current user
    if not transaction or transaction['user_id'] != session['user_id']:
        flash('Transaction not found')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        date = request.form['date']
        payee = request.form['payee']
        category_id = request.form['category_id']
        amount = float(request.form['amount'])
        memo = request.form['memo']
        
        # For expenses, make amount negative
        if 'expense' in request.form and request.form['expense'] == 'on':
            amount = -abs(amount)
        else:
            amount = abs(amount)
        
        modify_db('''
            UPDATE transactions
            SET date = ?, payee = ?, category_id = ?, amount = ?, memo = ?
            WHERE id = ?
        ''', [date, payee, category_id, amount, memo, transaction_id])
        
        flash('Transaction updated successfully')
        return redirect(url_for('view_budget', budget_id=transaction['budget_id']))
    
    # Get categories for this budget
    categories = query_db('SELECT * FROM categories WHERE budget_id = ?', [transaction['budget_id']])
    
    return render_template('edit_transaction.html', 
                           transaction=transaction,
                           categories=categories,
                           is_expense=transaction['amount'] < 0)

@app.route('/delete_transaction/<int:transaction_id>')
def delete_transaction(transaction_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Get the transaction
    transaction = query_db('''
        SELECT t.*, b.user_id FROM transactions t
        JOIN budgets b ON t.budget_id = b.id
        WHERE t.id = ?
    ''', [transaction_id], one=True)
    
    # Check if transaction exists and belongs to the current user
    if not transaction or transaction['user_id'] != session['user_id']:
        flash('Transaction not found')
        return redirect(url_for('index'))
    
    budget_id = transaction['budget_id']
    
    modify_db('DELETE FROM transactions WHERE id = ?', [transaction_id])
    
    flash('Transaction deleted successfully')
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/add_category', methods=['POST'])
def add_category():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    budget_id = request.form['budget_id']
    name = request.form['name']
    budget_amount = float(request.form['budget_amount'])
    
    modify_db('''
        INSERT INTO categories (budget_id, name, budget_amount)
        VALUES (?, ?, ?)
    ''', [budget_id, name, budget_amount])
    
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/edit_category/<int:category_id>', methods=['GET', 'POST'])
def edit_category(category_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Get the category
    category = query_db('''
        SELECT c.*, b.user_id FROM categories c
        JOIN budgets b ON c.budget_id = b.id
        WHERE c.id = ?
    ''', [category_id], one=True)
    
    # Check if category exists and belongs to the current user
    if not category or category['user_id'] != session['user_id']:
        flash('Category not found')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        budget_amount = float(request.form['budget_amount'])
        
        modify_db('''
            UPDATE categories
            SET name = ?, budget_amount = ?
            WHERE id = ?
        ''', [name, budget_amount, category_id])
        
        flash('Category updated successfully')
        return redirect(url_for('view_budget', budget_id=category['budget_id']))
    
    return render_template('edit_category.html', category=category)

@app.route('/delete_category/<int:category_id>')
def delete_category(category_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    # Get the category
    category = query_db('''
        SELECT c.*, b.user_id FROM categories c
        JOIN budgets b ON c.budget_id = b.id
        WHERE c.id = ?
    ''', [category_id], one=True)
    
    # Check if category exists and belongs to the current user
    if not category or category['user_id'] != session['user_id']:
        flash('Category not found')
        return redirect(url_for('index'))
    
    budget_id = category['budget_id']
    
    # Check if there are transactions using this category
    transactions = query_db('SELECT COUNT(*) as count FROM transactions WHERE category_id = ?', 
                            [category_id], one=True)
    
    if transactions['count'] > 0:
        flash('Cannot delete category with transactions. Please delete or reassign transactions first.')
    else:
        modify_db('DELETE FROM categories WHERE id = ?', [category_id])
        flash('Category deleted successfully')
    
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/update_budget', methods=['POST'])
def update_budget():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    budget_id = request.form['budget_id']
    
    # Check if budget belongs to the current user
    budget = query_db('SELECT * FROM budgets WHERE id = ? AND user_id = ?', 
                      [budget_id, session['user_id']], one=True)
    
    if not budget:
        flash('Budget not found')
        return redirect(url_for('index'))
    
    for key in request.form:
        if key.startswith('budget_'):
            category_id = int(key.split('_')[1])
            amount = float(request.form[key])
            
            modify_db('''
                UPDATE categories SET budget_amount = ?
                WHERE id = ? AND budget_id = ?
            ''', [amount, category_id, budget_id])
    
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/add_income', methods=['POST'])
def add_income():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    budget_id = request.form['budget_id']
    name = request.form['name']
    amount = float(request.form['amount'])
    frequency = request.form['frequency']
    start_date = request.form['start_date']
    end_date = request.form.get('end_date', '') or None  # Handle empty string

    modify_db('''
        INSERT INTO incomes (budget_id, name, amount, frequency, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', [budget_id, name, amount, frequency, start_date, end_date])

    flash('Income added successfully')
    return redirect(url_for('view_budget', budget_id=budget_id))

@app.route('/edit_income/<int:income_id>', methods=['GET', 'POST'])
def edit_income(income_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # Get the income
    income = query_db('''
        SELECT i.*, b.user_id FROM incomes i
        JOIN budgets b ON i.budget_id = b.id
        WHERE i.id = ?
    ''', [income_id], one=True)

    # Check if income exists and belongs to the current user
    if not income or income['user_id'] != session['user_id']:
        flash('Income not found')
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form['name']
        amount = float(request.form['amount'])
        frequency = request.form['frequency']
        start_date = request.form['start_date']
        end_date = request.form.get('end_date', '') or None  # Handle empty string

        modify_db('''
            UPDATE incomes
            SET name = ?, amount = ?, frequency = ?, start_date = ?, end_date = ?
            WHERE id = ?
        ''', [name, amount, frequency, start_date, end_date, income_id])

        flash('Income updated successfully')
        return redirect(url_for('view_budget', budget_id=income['budget_id']))

    return render_template('edit_income.html', income=income)

@app.route('/delete_income/<int:income_id>')
def delete_income(income_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # Get the income
    income = query_db('''
        SELECT i.*, b.user_id FROM incomes i
        JOIN budgets b ON i.budget_id = b.id
        WHERE i.id = ?
    ''', [income_id], one=True)

    # Check if income exists and belongs to the current user
    if not income or income['user_id'] != session['user_id']:
        flash('Income not found')
        return redirect(url_for('index'))

    budget_id = income['budget_id']

    modify_db('DELETE FROM incomes WHERE id = ?', [income_id])

    flash('Income deleted successfully')
    return redirect(url_for('view_budget', budget_id=budget_id))


if __name__ == '__main__':
    if not os.path.exists(app.config['DATABASE']):
        with open('schema.sql', 'w') as f:
            f.write('''
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
            ''')
        init_db()
        
        # Create test user and budget
        with app.app_context():
            modify_db('INSERT INTO users (username, password) VALUES (?, ?)', ['test', 'test'])
            modify_db('INSERT INTO budgets (user_id, name) VALUES (?, ?)', [1, 'Personal Budget'])
            
    app.run(debug=True)
