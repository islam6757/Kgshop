import os
import sqlite3
import secrets
from fastapi import FastAPI, Request, Form, File, UploadFile, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI()
security = HTTPBasic()

# Твои данные для входа в админку
ADMIN_USERNAME = "admin1"
ADMIN_PASSWORD = "admin1"  # Измени на свой надежный пароль

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

os.makedirs("static/images", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def init_db():
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            image_url TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price INTEGER NOT NULL,
            in_stock INTEGER NOT NULL DEFAULT 1,
            category_id INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            size TEXT DEFAULT '',
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ("Штаны", "/static/images/semiclassic.jpg"),
            ("Кроссовки", "/static/images/sneakers.jpg"),
            ("Футболки", "/static/images/tshirt.jpg"),
            ("Худи", "/static/images/hoodie.jpg"),
            ("Зипки", "/static/images/zip_hoodie.jpg"),
            ("Жилетки", "/static/images/vest.jpg"),
            ("Рубашки", "/static/images/shirt.jpg"),
            ("Полузамки", "/static/images/half_zip.jpg")
        ]
        cursor.executemany("INSERT INTO categories (title, image_url) VALUES (?, ?)", default_categories)
        
    cursor.execute("SELECT COUNT(*) FROM settings WHERE key = 'hero_image'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO settings (key, value) VALUES ('hero_image', '/static/images/hero.jpg')")
        
    conn.commit()
    conn.close()

init_db()

# --- КЛИЕНТСКАЯ ЧАСТЬ ---

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request, search: str = ""):
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, title, image_url FROM categories")
    categories = cursor.fetchall()
    
    cursor.execute("SELECT value FROM settings WHERE key = 'hero_image'")
    hero_result = cursor.fetchone()
    hero_image = hero_result[0] if hero_result else "/static/images/hero.jpg"
    
    products = []
    if search.strip():
        cursor.execute("""
            SELECT p.id, p.title, p.price, p.in_stock, p.image_url, c.title, p.size
            FROM products p 
            JOIN categories c ON p.category_id = c.id 
            WHERE p.title LIKE ?
        """, (f"%{search.strip()}%",))
        products = cursor.fetchall()
        
    conn.close()
    
    return templates.TemplateResponse(request, "index.html", {
        "categories": categories,
        "hero_image": hero_image,
        "products": products,
        "search_query": search
    })

@app.get("/api/search-suggestions")
async def search_suggestions(q: str = ""):
    if not q.strip():
        return JSONResponse([])
    
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT title FROM products 
        WHERE title LIKE ? 
        LIMIT 5
    """, (f"%{q.strip()}%",))
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return JSONResponse(results)

@app.get("/catalog/{category_id}", response_class=HTMLResponse)
async def category_catalog(request: Request, category_id: int, search: str = ""):
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT title FROM categories WHERE id = ?", (category_id,))
    cat_res = cursor.fetchone()
    category_name = cat_res[0] if cat_res else "Каталог"
    
    if search.strip():
        cursor.execute("""
            SELECT id, title, price, in_stock, image_url, size
            FROM products 
            WHERE category_id = ? AND title LIKE ?
        """, (category_id, f"%{search.strip()}%"))
    else:
        cursor.execute("""
            SELECT id, title, price, in_stock, image_url, size
            FROM products 
            WHERE category_id = ?
        """, (category_id,))
        
    products = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse(request, "catalog.html", {
        "category_name": category_name,
        "category_id": category_id,
        "products": products,
        "search_query": search
    })

# --- АДМИН-ПАНЕЛЬ (ЗАЩИЩЕНА ПАРОЛЕМ) ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, username: str = Depends(verify_admin)):
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, title, image_url FROM categories")
    categories = cursor.fetchall()
    
    cursor.execute("SELECT value FROM settings WHERE key = 'hero_image'")
    hero_result = cursor.fetchone()
    hero_image = hero_result[0] if hero_result else "/static/images/hero.jpg"
    
    cursor.execute("""
        SELECT p.id, p.title, p.price, p.in_stock, p.image_url, c.title, p.category_id, p.size
        FROM products p
        JOIN categories c ON p.category_id = c.id
        ORDER BY p.id DESC
    """)
    products = cursor.fetchall()
    
    conn.close()
    
    return templates.TemplateResponse(request, "admin.html", {
        "categories": categories,
        "hero_image": hero_image,
        "products": products
    })

@app.post("/admin/add-product")
async def add_product(
    title: str = Form(...),
    price: int = Form(...),
    category_id: int = Form(...),
    size: str = Form(""),  # <--- Добавили получение размера
    in_stock: int = Form(1),
    file: UploadFile = File(...),
    username: str = Depends(verify_admin)
):
    if file.filename:
        file_path = f"static/images/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        conn = sqlite3.connect("shop.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO products (title, price, in_stock, category_id, image_url, size)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, price, in_stock, category_id, f"/{file_path}", size))
        conn.commit()
        conn.close()

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update-product")
async def update_product(
    product_id: int = Form(...),
    price: int = Form(...),
    in_stock: int = Form(...),
    size: str = Form(""),
    username: str = Depends(verify_admin)
):
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE products SET price = ?, in_stock = ?, size = ? WHERE id = ?
    """, (price, in_stock, size, product_id))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete-product")
async def delete_product(
    product_id: int = Form(...),
    username: str = Depends(verify_admin)
):
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/admin", status_code=303)

# НОВЫЙ РОУТ: Добавление новой категории
@app.post("/admin/add-category")
async def add_category(
    name: str = Form(...),
    file: UploadFile = File(...),
    username: str = Depends(verify_admin)
):
    if file.filename:
        file_path = f"static/images/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        image_url = f"/{file_path}"
        conn = sqlite3.connect("shop.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO categories (title, image_url)
            VALUES (?, ?)
        """, (name, image_url))
        conn.commit()
        conn.close()

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update-category")
async def update_category(
    category_id: int = Form(...), 
    file: UploadFile = File(...),
    username: str = Depends(verify_admin)
):
    if file.filename:
        file_path = f"static/images/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        image_url = f"/{file_path}"
        conn = sqlite3.connect("shop.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE categories SET image_url = ? WHERE id = ?", (image_url, category_id))
        conn.commit()
        conn.close()

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update-hero")
async def update_hero(
    file: UploadFile = File(...),
    username: str = Depends(verify_admin)
):
    if file.filename:
        file_path = f"static/images/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        image_url = f"/{file_path}"
        conn = sqlite3.connect("shop.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'hero_image'", (image_url,))
        conn.commit()
        conn.close()

    return RedirectResponse(url="/admin", status_code=303)