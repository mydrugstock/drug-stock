from flask import Flask, render_template, request, redirect, url_for, flash
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime


# ==================================================
# ตั้งค่า Flask
# ==================================================

app = Flask(__name__)

app.secret_key = "drug-stock-secret"


# ==================================================
# เชื่อมต่อฐานข้อมูล Supabase
# ==================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


class DBConnection:

    def __init__(self):

        if not DATABASE_URL:
            raise RuntimeError(
                "ไม่พบ DATABASE_URL "
                "กรุณาตั้งค่า DATABASE_URL"
            )

        self.conn = psycopg2.connect(
            DATABASE_URL,
            sslmode="require"
        )

    def execute(self, sql, params=None):

        # แปลง ? แบบ SQLite
        # ให้เป็น %s แบบ PostgreSQL

        sql = sql.replace("?", "%s")

        cursor = self.conn.cursor(
            cursor_factory=RealDictCursor
        )

        cursor.execute(
            sql,
            params
        )

        return cursor

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    return DBConnection()


# ==================================================
# สร้างตาราง loan_units
#
# ระบบใหม่:
# ยืมทุกชนิด → แยกเป็นรายชิ้น
# ==================================================

_db_extension_initialized = False


def init_loan_units():

    global _db_extension_initialized

    if _db_extension_initialized:
        return

    conn = None

    try:

        conn = get_db()

        conn.execute("""
            CREATE TABLE IF NOT EXISTS loan_units
            (
                id SERIAL PRIMARY KEY,

                loan_id INTEGER NOT NULL
                    REFERENCES external_loans(id)
                    ON DELETE CASCADE,

                unit_number INTEGER NOT NULL,

                remaining_percent NUMERIC(5,2),

                used_quantity NUMERIC,

                returned_quantity NUMERIC,

                status VARCHAR(30)
                    DEFAULT 'ยังไม่คืน',

                return_date TIMESTAMP,

                UNIQUE(loan_id, unit_number)
            )
        """)

        conn.commit()

        # ==================================================
        # รองรับรายการยืมเก่าที่ยังไม่คืน
        # ==================================================

        old_loans = conn.execute("""
            SELECT
                external_loans.id,
                external_loans.quantity
            FROM external_loans
            WHERE external_loans.status = 'ยังไม่คืน'
              AND external_loans.quantity > 0
              AND external_loans.quantity = FLOOR(
                    external_loans.quantity
                  )
            ORDER BY external_loans.id
        """).fetchall()

        for loan in old_loans:

            unit_count = int(
                loan["quantity"]
            )

            for unit_number in range(
                1,
                unit_count + 1
            ):

                conn.execute("""
                    INSERT INTO loan_units
                    (
                        loan_id,
                        unit_number,
                        remaining_percent,
                        used_quantity,
                        returned_quantity,
                        status,
                        return_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (loan_id, unit_number)
                    DO NOTHING
                """, (
                    loan["id"],
                    unit_number,
                    None,
                    None,
                    None,
                    "ยังไม่คืน",
                    None
                ))

        conn.commit()

        _db_extension_initialized = True

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "ไม่สามารถสร้างตาราง loan_units:",
            e
        )

    finally:

        if conn:
            conn.close()


@app.before_request
def initialize_database_extensions():

    init_loan_units()


# ==================================================
# วันที่ปัจจุบัน
# ==================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ==================================================
# ระบบใหม่:
# ยืมทุกชนิดแยกเป็นรายชิ้น
# ==================================================

def is_individual_unit_drug(unit):

    return True


# ==================================================
# หน้าแรก
# ==================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ==================================================
# หน้ายืม / ขอ
# ==================================================

@app.route("/borrow")
def borrow():

    conn = get_db()

    drugs = conn.execute("""
        SELECT *
        FROM drugs
        ORDER BY name
    """).fetchall()

    conn.close()

    return render_template(
        "borrow.html",
        drugs=drugs
    )


# ==================================================
# หน้าสต๊อก
# ==================================================

@app.route("/stock")
def stock():

    conn = get_db()

    drugs = conn.execute("""
        SELECT *
        FROM drugs
        ORDER BY name
    """).fetchall()

    conn.close()

    return render_template(
        "stock.html",
        drugs=drugs
    )


# ==================================================
# เพิ่มยา
# ==================================================

@app.route("/add-drug", methods=["POST"])
def add_drug():

    try:

        name = request.form["name"].strip()

        quantity = float(
            request.form["quantity"]
        )

        unit = request.form["unit"].strip()

        min_quantity = float(
            request.form["min_quantity"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ กรุณากรอกข้อมูลให้ถูกต้อง"
        )

        return redirect(
            url_for("stock")
        )

    if name == "":

        flash(
            "❌ กรุณากรอกชื่อยา"
        )

        return redirect(
            url_for("stock")
        )

    if unit == "":

        flash(
            "❌ กรุณากรอกหน่วยยา"
        )

        return redirect(
            url_for("stock")
        )

    if quantity < 0:

        flash(
            "❌ จำนวนยาเริ่มต้นห้ามติดลบ"
        )

        return redirect(
            url_for("stock")
        )

    if min_quantity < 0:

        flash(
            "❌ จำนวนขั้นต่ำห้ามติดลบ"
        )

        return redirect(
            url_for("stock")
        )

    conn = get_db()

    try:

        # ==================================================
        # ตรวจชื่อยา + หน่วยยา
        # ==================================================

        existing = conn.execute("""
            SELECT *
            FROM drugs
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(unit)) = LOWER(TRIM(?))
            LIMIT 1
        """, (
            name,
            unit
        )).fetchone()

        # ==================================================
        # ถ้ามีอยู่แล้ว → รวมจำนวน
        # ==================================================

        if existing is not None:

            new_quantity = (
                existing["quantity"]
                + quantity
            )

            conn.execute("""
                UPDATE drugs
                SET
                    quantity = ?,
                    min_quantity = ?
                WHERE id = ?
            """, (
                new_quantity,
                min_quantity,
                existing["id"]
            ))

            conn.commit()

            flash(
                f"✅ พบ {existing['name']} "
                f"หน่วย {existing['unit']} อยู่แล้ว "
                f"จึงรวมจำนวนเพิ่ม {quantity:g} "
                f"{unit} | "
                f"คงเหลือ {new_quantity:g} {unit}"
            )

        # ==================================================
        # ถ้ายังไม่มี → สร้างใหม่
        # ==================================================

        else:

            conn.execute("""
                INSERT INTO drugs
                (
                    name,
                    quantity,
                    unit,
                    min_quantity
                )
                VALUES (?, ?, ?, ?)
            """, (
                name,
                quantity,
                unit,
                min_quantity
            ))

            conn.commit()

            flash(
                f"✅ เพิ่ม {name} "
                f"จำนวน {quantity:g} {unit} "
                f"เข้าสต๊อกแล้ว"
            )

    except Exception as e:

        conn.rollback()

        print(
            "ADD DRUG ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถเพิ่มยาได้"
        )

    finally:

        conn.close()

    return redirect(
        url_for("stock")
    )


# ==================================================
# ลบยา 1 รายการ
# ==================================================

@app.route("/delete-drug/<int:drug_id>", methods=["POST"])
def delete_drug(drug_id):

    conn = get_db()

    try:

        drug = conn.execute("""
            SELECT *
            FROM drugs
            WHERE id = ?
        """, (
            drug_id,
        )).fetchone()

        if drug is None:

            conn.close()

            flash(
                "❌ ไม่พบรายการยาที่ต้องการลบ"
            )

            return redirect(
                url_for("stock")
            )

        transaction_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM transactions
            WHERE drug_id = ?
        """, (
            drug_id,
        )).fetchone()["total"]

        loan_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM external_loans
            WHERE drug_id = ?
        """, (
            drug_id,
        )).fetchone()["total"]

        box_item_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM box_items
            WHERE drug_id = ?
        """, (
            drug_id,
        )).fetchone()["total"]

        box_unit_item_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM box_unit_items
            WHERE drug_id = ?
        """, (
            drug_id,
        )).fetchone()["total"]

        if (
            transaction_count > 0
            or loan_count > 0
            or box_item_count > 0
            or box_unit_item_count > 0
        ):

            conn.close()

            flash(
                f"❌ ไม่สามารถลบ {drug['name']} ได้ "
                f"เพราะรายการนี้มีประวัติการใช้งานแล้ว "
                f"เพื่อป้องกันประวัติย้อนหลังเสียหาย"
            )

            return redirect(
                url_for("stock")
            )

        conn.execute("""
            DELETE FROM drugs
            WHERE id = ?
        """, (
            drug_id,
        ))

        conn.commit()

        flash(
            f"🗑️ ลบ {drug['name']} "
            f"จำนวน {drug['quantity']:g} "
            f"{drug['unit']} ออกจากสต๊อกแล้ว"
        )

    except Exception as e:

        conn.rollback()

        print(
            "DELETE DRUG ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถลบรายการยาได้"
        )

    finally:

        conn.close()

    return redirect(
        url_for("stock")
    )


# ==================================================
# ยืม / ขอ
# ==================================================

@app.route("/request-drug", methods=["POST"])
def request_drug():

    try:

        requester = request.form[
            "requester"
        ].strip()

        drug_id = int(
            request.form["drug_id"]
        )

        quantity = float(
            request.form["quantity"]
        )

        transaction_type = request.form[
            "transaction_type"
        ]

    except (ValueError, KeyError):

        flash(
            "❌ ข้อมูลไม่ถูกต้อง"
        )

        return redirect(
            url_for("borrow")
        )

    if requester == "":

        flash(
            "❌ กรุณากรอกชื่อผู้ยืม/ผู้ขอ"
        )

        return redirect(
            url_for("borrow")
        )

    if quantity <= 0:

        flash(
            "❌ จำนวนต้องมากกว่า 0"
        )

        return redirect(
            url_for("borrow")
        )

    conn = get_db()

    try:

        drug = conn.execute("""
            SELECT *
            FROM drugs
            WHERE id = ?
            FOR UPDATE
        """, (
            drug_id,
        )).fetchone()

        if drug is None:

            conn.rollback()
            conn.close()

            flash(
                "❌ ไม่พบยาที่เลือก"
            )

            return redirect(
                url_for("borrow")
            )

        if quantity > drug["quantity"]:

            conn.rollback()
            conn.close()

            flash(
                f"❌ ยา {drug['name']} "
                f"มีในคลังเพียง "
                f"{drug['quantity']:g} "
                f"{drug['unit']}"
            )

            return redirect(
                url_for("borrow")
            )

        transaction_date = now()

        # ==================================================
        # ยืม
        # ==================================================

        if transaction_type == "ยืม":

            if not quantity.is_integer():

                conn.rollback()
                conn.close()

                flash(
                    f"❌ การยืมยาแบบรายชิ้น "
                    f"ต้องเป็นจำนวนเต็ม "
                    f"เช่น 1, 2, 5 {drug['unit']}"
                )

                return redirect(
                    url_for("borrow")
                )

            number_of_units = int(
                quantity
            )

            new_quantity = (
                drug["quantity"] - quantity
            )

            conn.execute("""
                UPDATE drugs
                SET quantity = ?
                WHERE id = ?
            """, (
                new_quantity,
                drug_id
            ))

            # ==================================================
            # สร้างรายการยืม
            # ==================================================

            cursor = conn.execute("""
                INSERT INTO external_loans
                (
                    borrower,
                    drug_id,
                    quantity,
                    remaining_percent,
                    used_quantity,
                    status,
                    borrow_date,
                    return_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, (
                requester,
                drug_id,
                quantity,
                None,
                None,
                "ยังไม่คืน",
                transaction_date,
                None
            ))

            loan_id = cursor.fetchone()["id"]

            # ==================================================
            # สร้าง loan_units
            # ==================================================

            for unit_number in range(
                1,
                number_of_units + 1
            ):

                conn.execute("""
                    INSERT INTO loan_units
                    (
                        loan_id,
                        unit_number,
                        remaining_percent,
                        used_quantity,
                        returned_quantity,
                        status,
                        return_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    loan_id,
                    unit_number,
                    None,
                    None,
                    None,
                    "ยังไม่คืน",
                    None
                ))

            # ==================================================
            # ประวัติการยืม
            # ==================================================

            conn.execute("""
                INSERT INTO transactions
                (
                    requester,
                    drug_id,
                    quantity,
                    transaction_type,
                    transaction_date,
                    cancelled,
                    loan_id,
                    box_loan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                requester,
                drug_id,
                quantity,
                "ยืม",
                transaction_date,
                0,
                loan_id,
                None
            ))

            conn.commit()
            conn.close()

            flash(
                f"✅ ยืม {drug['name']} "
                f"{quantity:g} {drug['unit']} สำเร็จ "
                f"| ระบบแยกติดตามเป็นรายชิ้น "
                f"{number_of_units} ชิ้นแล้ว"
            )

            return redirect(
                url_for("borrow")
            )

        # ==================================================
        # ขอ
        # ==================================================

        if transaction_type == "ขอ":

            new_quantity = (
                drug["quantity"] - quantity
            )

            conn.execute("""
                UPDATE drugs
                SET quantity = ?
                WHERE id = ?
            """, (
                new_quantity,
                drug_id
            ))

            conn.execute("""
                INSERT INTO transactions
                (
                    requester,
                    drug_id,
                    quantity,
                    transaction_type,
                    transaction_date,
                    cancelled,
                    loan_id,
                    box_loan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                requester,
                drug_id,
                quantity,
                "ขอ",
                transaction_date,
                0,
                None,
                None
            ))

            conn.commit()
            conn.close()

            flash(
                f"✅ ขอ {drug['name']} "
                f"{quantity:g} {drug['unit']} สำเร็จ"
            )

            return redirect(
                url_for("borrow")
            )

        conn.rollback()
        conn.close()

        flash(
            "❌ ไม่พบประเภทการทำรายการ"
        )

        return redirect(
            url_for("borrow")
        )

    except Exception as e:

        conn.rollback()
        conn.close()

        print(
            "REQUEST DRUG ERROR:",
            e
        )

        flash(
            "❌ เกิดข้อผิดพลาดในการทำรายการ"
        )

        return redirect(
            url_for("borrow")
        )


# ==================================================
# ระบบจัดกล่อง
# ==================================================

@app.route("/box")
def box():

    conn = get_db()

    drugs = conn.execute("""
        SELECT *
        FROM drugs
        ORDER BY name
    """).fetchall()

    box_items = conn.execute("""
        SELECT
            box_items.id,
            box_items.drug_id,
            box_items.quantity_per_box,
            drugs.name AS drug_name,
            drugs.unit AS drug_unit
        FROM box_items
        JOIN drugs
            ON box_items.drug_id = drugs.id
        ORDER BY drugs.name
    """).fetchall()

    box_loans = conn.execute("""
        SELECT
            id,
            borrower,
            total_boxes,
            returned_boxes,
            (
                total_boxes - returned_boxes
            ) AS remaining_boxes,
            status,
            borrow_date,
            return_date
        FROM box_loans
        WHERE status = 'รอคืน'
        ORDER BY id DESC
    """).fetchall()

    box_units = conn.execute("""
        SELECT
            box_units.id,
            box_units.box_loan_id,
            box_units.box_number,
            box_units.status,
            box_units.borrow_date,
            box_loans.borrower
        FROM box_units
        JOIN box_loans
            ON box_units.box_loan_id = box_loans.id
        WHERE box_units.status = 'รอคืน'
        ORDER BY
            box_units.box_loan_id DESC,
            box_units.box_number ASC
    """).fetchall()

    conn.close()

    return render_template(
        "box.html",
        drugs=drugs,
        box_items=box_items,
        box_loans=box_loans,
        box_units=box_units
    )


# ==================================================
# บันทึกสูตรกล่อง
# ==================================================

@app.route("/save-box-template", methods=["POST"])
def save_box_template():

    drug_ids = request.form.getlist(
        "drug_id[]"
    )

    quantities = request.form.getlist(
        "quantity_per_box[]"
    )

    if len(drug_ids) == 0:

        flash(
            "❌ กรุณาเพิ่มยาอย่างน้อย 1 รายการ"
        )

        return redirect(
            url_for("box")
        )

    if len(drug_ids) != len(quantities):

        flash(
            "❌ ข้อมูลยาไม่ครบ"
        )

        return redirect(
            url_for("box")
        )

    conn = get_db()

    try:

        active = conn.execute("""
            SELECT COUNT(*) AS total
            FROM box_units
            WHERE status = 'รอคืน'
        """).fetchone()

        if active["total"] > 0:

            conn.close()

            flash(
                "❌ ยังมีกล่องที่รอคืนอยู่ "
                "กรุณาคืนกล่องให้ครบก่อนเปลี่ยนสูตร"
            )

            return redirect(
                url_for("box")
            )

        conn.execute("""
            DELETE FROM box_items
        """)

        used_drugs = set()

        for drug_id_text, quantity_text in zip(
            drug_ids,
            quantities
        ):

            try:

                drug_id = int(
                    drug_id_text
                )

                quantity = float(
                    quantity_text
                )

            except ValueError:

                conn.rollback()
                conn.close()

                flash(
                    "❌ ข้อมูลจำนวนยาไม่ถูกต้อง"
                )

                return redirect(
                    url_for("box")
                )

            if quantity <= 0:

                conn.rollback()
                conn.close()

                flash(
                    "❌ จำนวนต่อกล่องต้องมากกว่า 0"
                )

                return redirect(
                    url_for("box")
                )

            if drug_id in used_drugs:

                conn.rollback()
                conn.close()

                flash(
                    "❌ ไม่ควรเลือกยาชนิดเดียวกันซ้ำ"
                )

                return redirect(
                    url_for("box")
                )

            used_drugs.add(
                drug_id
            )

            drug = conn.execute("""
                SELECT id
                FROM drugs
                WHERE id = ?
            """, (
                drug_id,
            )).fetchone()

            if drug is None:

                conn.rollback()
                conn.close()

                flash(
                    "❌ ไม่พบยาที่เลือก"
                )

                return redirect(
                    url_for("box")
                )

            conn.execute("""
                INSERT INTO box_items
                (
                    drug_id,
                    quantity_per_box
                )
                VALUES (?, ?)
            """, (
                drug_id,
                quantity
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "SAVE BOX TEMPLATE ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถบันทึกสูตรกล่องได้"
        )

    finally:

        conn.close()

    flash(
        "✅ บันทึกสูตร 1 กล่องเรียบร้อย"
    )

    return redirect(
        url_for("box")
    )


# ==================================================
# รีเซ็ตสูตรกล่อง
# ==================================================

@app.route("/reset-box-template", methods=["POST"])
def reset_box_template():

    conn = get_db()

    active = conn.execute("""
        SELECT COUNT(*) AS total
        FROM box_units
        WHERE status = 'รอคืน'
    """).fetchone()

    if active["total"] > 0:

        conn.close()

        flash(
            "❌ ยังมีกล่องที่รอคืนอยู่ "
            "กรุณาคืนกล่องให้ครบก่อน"
        )

        return redirect(
            url_for("box")
        )

    conn.execute("""
        DELETE FROM box_items
    """)

    conn.commit()
    conn.close()

    flash(
        "🗑️ รีเซ็ตสูตรกล่องแล้ว"
    )

    return redirect(
        url_for("box")
    )


# ==================================================
# สร้างกล่อง 1 ใบ
# ==================================================

@app.route("/create-box", methods=["POST"])
def create_box():

    borrower = request.form[
        "borrower"
    ].strip()

    if borrower == "":

        flash(
            "❌ กรุณากรอกชื่อผู้ยืม"
        )

        return redirect(
            url_for("box")
        )

    conn = get_db()

    try:

        box_items = conn.execute("""
            SELECT
                box_items.drug_id,
                box_items.quantity_per_box,
                drugs.name AS drug_name,
                drugs.unit AS drug_unit,
                drugs.quantity AS stock_quantity
            FROM box_items
            JOIN drugs
                ON box_items.drug_id = drugs.id
            ORDER BY drugs.name
        """).fetchall()

        if len(box_items) == 0:

            conn.close()

            flash(
                "❌ ยังไม่ได้กำหนดสูตรกล่อง"
            )

            return redirect(
                url_for("box")
            )

        for item in box_items:

            if (
                item["quantity_per_box"]
                > item["stock_quantity"]
            ):

                conn.close()

                flash(
                    f"❌ จัดกล่องไม่ได้! "
                    f"{item['drug_name']} "
                    f"มี {item['stock_quantity']:g} "
                    f"{item['drug_unit']} "
                    f"แต่กล่องต้องใช้ "
                    f"{item['quantity_per_box']:g}"
                )

                return redirect(
                    url_for("box")
                )

        transaction_date = now()

        cursor = conn.execute("""
            INSERT INTO box_loans
            (
                borrower,
                total_boxes,
                returned_boxes,
                status,
                borrow_date,
                return_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            borrower,
            1,
            0,
            "รอคืน",
            transaction_date,
            None
        ))

        box_loan_id = cursor.fetchone()["id"]

        cursor = conn.execute("""
            INSERT INTO box_units
            (
                box_loan_id,
                box_number,
                status,
                borrow_date,
                return_date
            )
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
        """, (
            box_loan_id,
            1,
            "รอคืน",
            transaction_date,
            None
        ))

        box_unit_id = cursor.fetchone()["id"]

        for item in box_items:

            conn.execute("""
                UPDATE drugs
                SET quantity = quantity - ?
                WHERE id = ?
            """, (
                item["quantity_per_box"],
                item["drug_id"]
            ))

            conn.execute("""
                INSERT INTO box_unit_items
                (
                    box_unit_id,
                    drug_id,
                    original_quantity,
                    remaining_quantity,
                    used_quantity,
                    returned_quantity
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                box_unit_id,
                item["drug_id"],
                item["quantity_per_box"],
                None,
                None,
                None
            ))

            conn.execute("""
                INSERT INTO transactions
                (
                    requester,
                    drug_id,
                    quantity,
                    transaction_type,
                    transaction_date,
                    cancelled,
                    loan_id,
                    box_loan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                borrower,
                item["drug_id"],
                item["quantity_per_box"],
                "ยืมกล่อง",
                transaction_date,
                0,
                None,
                box_loan_id
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "CREATE BOX ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถสร้างกล่องได้"
        )

        conn.close()

        return redirect(
            url_for("box")
        )

    conn.close()

    flash(
        "📦 จัดกล่องที่ 1 สำเร็จ | "
        f"ผู้ยืม: {borrower}"
    )

    return redirect(
        url_for("box")
    )


# ==================================================
# เพิ่มจำนวนกล่อง
# ==================================================

@app.route("/add-box", methods=["POST"])
def add_box():

    try:

        box_loan_id = int(
            request.form["box_loan_id"]
        )

        add_boxes = int(
            request.form["add_boxes"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ จำนวนกล่องไม่ถูกต้อง"
        )

        return redirect(
            url_for("box")
        )

    if add_boxes <= 0:

        flash(
            "❌ จำนวนกล่องต้องมากกว่า 0"
        )

        return redirect(
            url_for("box")
        )

    conn = get_db()

    try:

        box_loan = conn.execute("""
            SELECT *
            FROM box_loans
            WHERE id = ?
            AND status = 'รอคืน'
        """, (
            box_loan_id,
        )).fetchone()

        if box_loan is None:

            conn.close()

            flash(
                "❌ ไม่พบชุดกล่องนี้"
            )

            return redirect(
                url_for("box")
            )

        box_items = conn.execute("""
            SELECT
                box_items.drug_id,
                box_items.quantity_per_box,
                drugs.name AS drug_name,
                drugs.unit AS drug_unit,
                drugs.quantity AS stock_quantity
            FROM box_items
            JOIN drugs
                ON box_items.drug_id = drugs.id
            ORDER BY drugs.name
        """).fetchall()

        if len(box_items) == 0:

            conn.close()

            flash(
                "❌ ยังไม่ได้กำหนดสูตรกล่อง"
            )

            return redirect(
                url_for("box")
            )

        for item in box_items:

            required = (
                item["quantity_per_box"]
                * add_boxes
            )

            if required > item["stock_quantity"]:

                conn.close()

                flash(
                    f"❌ เพิ่มกล่องไม่ได้! "
                    f"{item['drug_name']} "
                    f"ต้องใช้เพิ่ม {required:g} "
                    f"{item['drug_unit']} "
                    f"แต่มี {item['stock_quantity']:g}"
                )

                return redirect(
                    url_for("box")
                )

        transaction_date = now()

        latest = conn.execute("""
            SELECT MAX(box_number) AS max_number
            FROM box_units
            WHERE box_loan_id = ?
        """, (
            box_loan_id,
        )).fetchone()

        next_box_number = (
            latest["max_number"] or 0
        ) + 1

        for i in range(add_boxes):

            box_number = (
                next_box_number + i
            )

            cursor = conn.execute("""
                INSERT INTO box_units
                (
                    box_loan_id,
                    box_number,
                    status,
                    borrow_date,
                    return_date
                )
                VALUES (?, ?, ?, ?, ?)
                RETURNING id
            """, (
                box_loan_id,
                box_number,
                "รอคืน",
                transaction_date,
                None
            ))

            box_unit_id = cursor.fetchone()["id"]

            for item in box_items:

                required = item[
                    "quantity_per_box"
                ]

                conn.execute("""
                    UPDATE drugs
                    SET quantity = quantity - ?
                    WHERE id = ?
                """, (
                    required,
                    item["drug_id"]
                ))

                conn.execute("""
                    INSERT INTO box_unit_items
                    (
                        box_unit_id,
                        drug_id,
                        original_quantity,
                        remaining_quantity,
                        used_quantity,
                        returned_quantity
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    box_unit_id,
                    item["drug_id"],
                    required,
                    None,
                    None,
                    None
                ))

                conn.execute("""
                    INSERT INTO transactions
                    (
                        requester,
                        drug_id,
                        quantity,
                        transaction_type,
                        transaction_date,
                        cancelled,
                        loan_id,
                        box_loan_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    box_loan["borrower"],
                    item["drug_id"],
                    required,
                    "เพิ่มกล่อง",
                    transaction_date,
                    0,
                    None,
                    box_loan_id
                ))

        new_total = (
            box_loan["total_boxes"]
            + add_boxes
        )

        conn.execute("""
            UPDATE box_loans
            SET total_boxes = ?
            WHERE id = ?
        """, (
            new_total,
            box_loan_id
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "ADD BOX ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถเพิ่มกล่องได้"
        )

        conn.close()

        return redirect(
            url_for("box")
        )

    conn.close()

    flash(
        f"📦 เพิ่ม {add_boxes} กล่องสำเร็จ | "
        f"รวมทั้งหมด {new_total} กล่อง"
    )

    return redirect(
        url_for("box")
    )


# ==================================================
# หน้า "คืนกล่อง"
# ==================================================

@app.route("/return-box/<int:box_unit_id>")
def return_box_page(box_unit_id):

    conn = get_db()

    box_unit = conn.execute("""
        SELECT
            box_units.*,
            box_loans.borrower,
            box_loans.id AS loan_id
        FROM box_units
        JOIN box_loans
            ON box_units.box_loan_id = box_loans.id
        WHERE box_units.id = ?
        AND box_units.status = 'รอคืน'
    """, (
        box_unit_id,
    )).fetchone()

    if box_unit is None:

        conn.close()

        flash(
            "❌ ไม่พบกล่อง หรือกล่องนี้คืนแล้ว"
        )

        return redirect(
            url_for("box")
        )

    items = conn.execute("""
        SELECT
            box_unit_items.id,
            box_unit_items.drug_id,
            box_unit_items.original_quantity,
            drugs.name AS drug_name,
            drugs.unit AS drug_unit
        FROM box_unit_items
        JOIN drugs
            ON box_unit_items.drug_id = drugs.id
        WHERE box_unit_items.box_unit_id = ?
        ORDER BY drugs.name
    """, (
        box_unit_id,
    )).fetchall()

    conn.close()

    return render_template(
        "return_box.html",
        box_unit=box_unit,
        items=items
    )


# ==================================================
# ยืนยันคืนกล่อง
# ==================================================

@app.route("/return-box", methods=["POST"])
def return_box():

    box_unit_id_text = request.form.get(
        "box_unit_id"
    )

    if not box_unit_id_text:

        flash(
            "❌ ไม่พบรหัสกล่อง "
            "กรุณาเข้าหน้าคืนกล่องใหม่"
        )

        return redirect(
            url_for("box")
        )

    try:

        box_unit_id = int(
            box_unit_id_text
        )

    except ValueError:

        flash(
            "❌ รหัสกล่องไม่ถูกต้อง"
        )

        return redirect(
            url_for("box")
        )

    conn = get_db()

    try:

        box_unit = conn.execute("""
            SELECT
                box_units.*,
                box_loans.borrower,
                box_loans.total_boxes,
                box_loans.returned_boxes
            FROM box_units
            JOIN box_loans
                ON box_units.box_loan_id = box_loans.id
            WHERE box_units.id = ?
            AND box_units.status = 'รอคืน'
        """, (
            box_unit_id,
        )).fetchone()

        if box_unit is None:

            conn.close()

            flash(
                "❌ ไม่พบกล่อง หรือกล่องนี้คืนแล้ว"
            )

            return redirect(
                url_for("box")
            )

        items = conn.execute("""
            SELECT
                box_unit_items.*,
                drugs.name AS drug_name,
                drugs.unit AS drug_unit,
                drugs.quantity AS stock_quantity
            FROM box_unit_items
            JOIN drugs
                ON box_unit_items.drug_id = drugs.id
            WHERE box_unit_items.box_unit_id = ?
            ORDER BY drugs.name
        """, (
            box_unit_id,
        )).fetchall()

        if len(items) == 0:

            conn.close()

            flash(
                "❌ ไม่พบยาในกล่อง"
            )

            return redirect(
                url_for("box")
            )

        return_data = []

        for item in items:

            field_name = (
                f"remaining_{item['id']}"
            )

            value = request.form.get(
                field_name
            )

            if value is None or value.strip() == "":

                conn.rollback()
                conn.close()

                flash(
                    f"❌ กรุณากรอกจำนวนยา "
                    f"{item['drug_name']}"
                )

                return redirect(
                    url_for(
                        "return_box_page",
                        box_unit_id=box_unit_id
                    )
                )

            try:

                remaining = float(value)

            except ValueError:

                conn.rollback()
                conn.close()

                flash(
                    f"❌ จำนวนยา "
                    f"{item['drug_name']} "
                    f"ไม่ถูกต้อง"
                )

                return redirect(
                    url_for(
                        "return_box_page",
                        box_unit_id=box_unit_id
                    )
                )

            if remaining < 0:

                conn.rollback()
                conn.close()

                flash(
                    f"❌ {item['drug_name']} "
                    f"จำนวนที่เหลือห้ามติดลบ"
                )

                return redirect(
                    url_for(
                        "return_box_page",
                        box_unit_id=box_unit_id
                    )
                )

            if remaining > item["original_quantity"]:

                conn.rollback()
                conn.close()

                flash(
                    f"❌ {item['drug_name']} "
                    f"เหลือได้ไม่เกิน "
                    f"{item['original_quantity']:g} "
                    f"{item['drug_unit']}"
                )

                return redirect(
                    url_for(
                        "return_box_page",
                        box_unit_id=box_unit_id
                    )
                )

            used = (
                item["original_quantity"]
                - remaining
            )

            returned = remaining

            return_data.append({
                "item": item,
                "remaining": remaining,
                "used": used,
                "returned": returned
            })

        transaction_date = now()

        for data in return_data:

            item = data["item"]

            remaining = data["remaining"]

            used = data["used"]

            returned = data["returned"]

            conn.execute("""
                UPDATE drugs
                SET quantity = quantity + ?
                WHERE id = ?
            """, (
                returned,
                item["drug_id"]
            ))

            conn.execute("""
                UPDATE box_unit_items
                SET
                    remaining_quantity = ?,
                    used_quantity = ?,
                    returned_quantity = ?
                WHERE id = ?
            """, (
                remaining,
                used,
                returned,
                item["id"]
            ))

            conn.execute("""
                INSERT INTO transactions
                (
                    requester,
                    drug_id,
                    quantity,
                    transaction_type,
                    transaction_date,
                    cancelled,
                    loan_id,
                    box_loan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                box_unit["borrower"],
                item["drug_id"],
                returned,
                "คืนกล่อง",
                transaction_date,
                0,
                None,
                box_unit["box_loan_id"]
            ))

        conn.execute("""
            UPDATE box_units
            SET
                status = 'คืนแล้ว',
                return_date = ?
            WHERE id = ?
        """, (
            transaction_date,
            box_unit_id
        ))

        loan_id = box_unit[
            "box_loan_id"
        ]

        count_result = conn.execute("""
            SELECT
                COUNT(*) AS total_boxes,
                SUM(
                    CASE
                        WHEN status = 'คืนแล้ว'
                        THEN 1
                        ELSE 0
                    END
                ) AS returned_boxes
            FROM box_units
            WHERE box_loan_id = ?
        """, (
            loan_id,
        )).fetchone()

        total_boxes = count_result[
            "total_boxes"
        ]

        returned_boxes = (
            count_result["returned_boxes"]
            or 0
        )

        if returned_boxes == total_boxes:

            conn.execute("""
                UPDATE box_loans
                SET
                    returned_boxes = ?,
                    status = 'คืนแล้ว',
                    return_date = ?
                WHERE id = ?
            """, (
                returned_boxes,
                transaction_date,
                loan_id
            ))

        else:

            conn.execute("""
                UPDATE box_loans
                SET returned_boxes = ?
                WHERE id = ?
            """, (
                returned_boxes,
                loan_id
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "RETURN BOX ERROR:",
            e
        )

        flash(
            "❌ เกิดข้อผิดพลาดในการคืนกล่อง"
        )

        conn.close()

        return redirect(
            url_for("box")
        )

    conn.close()

    flash(
        f"✅ คืนกล่องที่ "
        f"{box_unit['box_number']} สำเร็จ | "
        f"ผู้ยืม: {box_unit['borrower']} | "
        f"คืนแล้ว {returned_boxes}/{total_boxes} กล่อง"
    )

    return redirect(
        url_for("box")
    )


# ==================================================
# หน้าคืนยาภายนอก
# ==================================================

@app.route("/return")
def return_drug():

    conn = get_db()

    loans = conn.execute("""
        SELECT
            external_loans.*,
            drugs.name AS drug_name,
            drugs.unit AS drug_unit
        FROM external_loans
        JOIN drugs
            ON external_loans.drug_id = drugs.id
        WHERE external_loans.status = 'ยังไม่คืน'
        ORDER BY external_loans.borrow_date DESC
    """).fetchall()

    # ==================================================
    # ทุกยาเป็นรายชิ้น
    # ==================================================

    for loan in loans:

        loan["is_tube"] = True

        loan_units = conn.execute("""
            SELECT *
            FROM loan_units
            WHERE loan_id = ?
            AND status = 'ยังไม่คืน'
            ORDER BY unit_number
        """, (
            loan["id"],
        )).fetchall()

        loan["loan_units"] = loan_units

    conn.close()

    return render_template(
        "return.html",
        loans=loans
    )


# ==================================================
# รับคืนยาภายนอก
# ==================================================

@app.route("/return-drug", methods=["POST"])
def return_drug_submit():

    try:

        loan_id = int(
            request.form["loan_id"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ ข้อมูลการคืนยาไม่ถูกต้อง"
        )

        return redirect(
            url_for("return_drug")
        )

    conn = get_db()

    try:

        loan = conn.execute("""
            SELECT
                external_loans.*,
                drugs.name AS drug_name,
                drugs.unit AS drug_unit,
                drugs.quantity AS stock_quantity
            FROM external_loans
            JOIN drugs
                ON external_loans.drug_id = drugs.id
            WHERE external_loans.id = ?
            AND external_loans.status = 'ยังไม่คืน'
            FOR UPDATE
        """, (
            loan_id,
        )).fetchone()

        if loan is None:

            conn.rollback()
            conn.close()

            flash(
                "❌ ไม่พบรายการยืม"
            )

            return redirect(
                url_for("return_drug")
            )

        units = conn.execute("""
            SELECT *
            FROM loan_units
            WHERE loan_id = ?
            AND status = 'ยังไม่คืน'
            ORDER BY unit_number
        """, (
            loan_id,
        )).fetchall()

        if len(units) == 0:

            conn.rollback()
            conn.close()

            flash(
                "❌ ไม่พบข้อมูลยารายชิ้น "
                "ของรายการยืมนี้"
            )

            return redirect(
                url_for("return_drug")
            )

        return_data = []

        total_returned = 0
        total_used = 0
        total_percent = 0

        # ==================================================
        # อ่านเปอร์เซ็นต์ทีละชิ้น
        # ==================================================

        for unit in units:

            field_name = (
                f"unit_{unit['id']}"
            )

            value = request.form.get(
                field_name
            )

            if value is None or value.strip() == "":

                conn.rollback()
                conn.close()

                flash(
                    f"❌ กรุณากรอกเปอร์เซ็นต์ "
                    f"ของ {loan['drug_unit']} "
                    f"ที่ {unit['unit_number']}"
                )

                return redirect(
                    url_for("return_drug")
                )

            try:

                remaining_percent = float(
                    value
                )

            except ValueError:

                conn.rollback()
                conn.close()

                flash(
                    f"❌ เปอร์เซ็นต์ของ "
                    f"{loan['drug_unit']} "
                    f"ที่ {unit['unit_number']} "
                    f"ไม่ถูกต้อง"
                )

                return redirect(
                    url_for("return_drug")
                )

            if (
                remaining_percent < 0
                or remaining_percent > 100
            ):

                conn.rollback()
                conn.close()

                flash(
                    f"❌ {loan['drug_unit']} "
                    f"ที่ {unit['unit_number']} "
                    f"ต้องอยู่ระหว่าง 0–100%"
                )

                return redirect(
                    url_for("return_drug")
                )

            # ==================================================
            # แต่ละชิ้น = 1 หน่วย
            # ==================================================

            returned_quantity = (
                remaining_percent / 100
            )

            used_quantity = (
                1 - returned_quantity
            )

            return_data.append({
                "unit": unit,
                "remaining_percent":
                    remaining_percent,
                "returned_quantity":
                    returned_quantity,
                "used_quantity":
                    used_quantity
            })

            total_returned += (
                returned_quantity
            )

            total_used += (
                used_quantity
            )

            total_percent += (
                remaining_percent
            )

        # ==================================================
        # เพิ่มของที่เหลือกลับเข้าสต๊อก
        # ==================================================

        new_stock = (
            loan["stock_quantity"]
            + total_returned
        )

        conn.execute("""
            UPDATE drugs
            SET quantity = ?
            WHERE id = ?
        """, (
            new_stock,
            loan["drug_id"]
        ))

        return_date = now()

        # ==================================================
        # บันทึกแต่ละชิ้น
        # ==================================================

        for data in return_data:

            unit = data["unit"]

            remaining_percent = data[
                "remaining_percent"
            ]

            returned_quantity = data[
                "returned_quantity"
            ]

            used_quantity = data[
                "used_quantity"
            ]

            conn.execute("""
                UPDATE loan_units
                SET
                    remaining_percent = ?,
                    used_quantity = ?,
                    returned_quantity = ?,
                    status = 'คืนแล้ว',
                    return_date = ?
                WHERE id = ?
            """, (
                remaining_percent,
                used_quantity,
                returned_quantity,
                return_date,
                unit["id"]
            ))

            # ==================================================
            # ประวัติการคืน
            # ==================================================

            conn.execute("""
                INSERT INTO transactions
                (
                    requester,
                    drug_id,
                    quantity,
                    transaction_type,
                    transaction_date,
                    cancelled,
                    loan_id,
                    box_loan_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                loan["borrower"],
                loan["drug_id"],
                returned_quantity,
                (
                    f"คืนรายการที่ "
                    f"{unit['unit_number']} "
                    f"({remaining_percent:g}%)"
                ),
                return_date,
                0,
                loan_id,
                None
            ))

        # ==================================================
        # ค่าเฉลี่ยเปอร์เซ็นต์
        # ==================================================

        average_percent = (
            total_percent / len(units)
        )

        # ==================================================
        # อัปเดต external_loans
        # ==================================================

        conn.execute("""
            UPDATE external_loans
            SET
                remaining_percent = ?,
                used_quantity = ?,
                status = 'คืนแล้ว',
                return_date = ?
            WHERE id = ?
        """, (
            average_percent,
            total_used,
            return_date,
            loan_id
        ))

        conn.commit()
        conn.close()

        flash(
            f"✅ คืน {loan['drug_name']} "
            f"{loan['quantity']:g} "
            f"{loan['drug_unit']} สำเร็จ | "
            f"คืนเข้าสต๊อก {total_returned:g} "
            f"{loan['drug_unit']} | "
            f"ใช้ไป {total_used:g} "
            f"{loan['drug_unit']}"
        )

        return redirect(
            url_for("return_drug")
        )

    except Exception as e:

        conn.rollback()

        print(
            "RETURN DRUG ERROR:",
            e
        )

        conn.close()

        flash(
            "❌ เกิดข้อผิดพลาดในการคืนยา"
        )

        return redirect(
            url_for("return_drug")
        )


# ==================================================
# รายงาน
# ==================================================

@app.route("/report")
def report():

    conn = get_db()

    transactions = conn.execute("""
        SELECT
            transactions.id,
            transactions.requester,
            transactions.drug_id,
            transactions.quantity,
            transactions.transaction_type,
            transactions.transaction_date,
            transactions.cancelled,
            transactions.loan_id,
            transactions.box_loan_id,
            drugs.name AS drug_name,
            drugs.unit AS drug_unit
        FROM transactions
        LEFT JOIN drugs
            ON transactions.drug_id = drugs.id
        ORDER BY transactions.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "report.html",
        transactions=transactions
    )


# ==================================================
# ลบประวัติรายการ
#
# ลบเฉพาะประวัติในหน้า "รายงาน"
# ไม่คืนสต๊อก
# ไม่เปลี่ยนสถานะการยืม
# ==================================================

@app.route("/delete-transaction", methods=["POST"])
def delete_transaction():

    try:

        transaction_id = int(
            request.form["transaction_id"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ รหัสรายการไม่ถูกต้อง"
        )

        return redirect(
            url_for("report")
        )

    conn = get_db()

    try:

        transaction = conn.execute("""
            SELECT *
            FROM transactions
            WHERE id = ?
        """, (
            transaction_id,
        )).fetchone()

        if transaction is None:

            conn.close()

            flash(
                "❌ ไม่พบประวัติรายการที่ต้องการลบ"
            )

            return redirect(
                url_for("report")
            )

        conn.execute("""
            DELETE FROM transactions
            WHERE id = ?
        """, (
            transaction_id,
        ))

        conn.commit()
        conn.close()

        flash(
            "🗑️ ลบประวัติรายการเรียบร้อยแล้ว"
        )

        return redirect(
            url_for("report")
        )

    except Exception as e:

        conn.rollback()

        print(
            "DELETE TRANSACTION ERROR:",
            e
        )

        conn.close()

        flash(
            "❌ ไม่สามารถลบประวัติรายการได้"
        )

        return redirect(
            url_for("report")
        )


# ==================================================
# ยกเลิกรายการ
# ==================================================

@app.route("/cancel-transaction", methods=["POST"])
def cancel_transaction():

    try:

        transaction_id = int(
            request.form["transaction_id"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ รหัสรายการไม่ถูกต้อง"
        )

        return redirect(
            url_for("report")
        )

    conn = get_db()

    try:

        transaction = conn.execute("""
            SELECT
                transactions.*,
                drugs.name AS drug_name,
                drugs.unit AS drug_unit,
                drugs.quantity AS stock_quantity
            FROM transactions
            LEFT JOIN drugs
                ON transactions.drug_id = drugs.id
            WHERE transactions.id = ?
        """, (
            transaction_id,
        )).fetchone()

        if transaction is None:

            conn.close()

            flash(
                "❌ ไม่พบรายการ"
            )

            return redirect(
                url_for("report")
            )

        if transaction["cancelled"] == 1:

            conn.close()

            flash(
                "⚠️ รายการนี้ถูกยกเลิกแล้ว"
            )

            return redirect(
                url_for("report")
            )

        # ==================================================
        # ห้ามยกเลิกรายการคืน
        # ==================================================

        transaction_type = str(
            transaction["transaction_type"]
        )

        if (
            transaction_type == "คืน"
            or
            transaction_type == "คืนกล่อง"
            or
            transaction_type.startswith("คืน")
        ):

            conn.close()

            flash(
                "❌ ไม่สามารถยกเลิกรายการคืนได้"
            )

            return redirect(
                url_for("report")
            )

        # ==================================================
        # รายการกล่อง
        # ==================================================

        if transaction["box_loan_id"] is not None:

            conn.close()

            flash(
                "❌ รายการกล่อง "
                "ให้จัดการผ่านเมนู 📦 จัดกล่อง"
            )

            return redirect(
                url_for("report")
            )

        # ==================================================
        # ตรวจสอบรายการยืม
        # ==================================================

        if transaction["transaction_type"] == "ยืม":

            if transaction["loan_id"] is not None:

                loan = conn.execute("""
                    SELECT *
                    FROM external_loans
                    WHERE id = ?
                """, (
                    transaction["loan_id"],
                )).fetchone()

                if loan is not None:

                    if loan["status"] != "ยังไม่คืน":

                        conn.close()

                        flash(
                            "❌ รายการนี้ถูกคืนหรือยกเลิกแล้ว"
                        )

                        return redirect(
                            url_for("report")
                        )

        if transaction["stock_quantity"] is None:

            conn.close()

            flash(
                "❌ ไม่พบรายการยาในสต๊อก"
            )

            return redirect(
                url_for("report")
            )

        # ==================================================
        # คืนจำนวนเข้าสต๊อก
        # ==================================================

        new_stock = (
            transaction["stock_quantity"]
            + transaction["quantity"]
        )

        conn.execute("""
            UPDATE drugs
            SET quantity = ?
            WHERE id = ?
        """, (
            new_stock,
            transaction["drug_id"]
        ))

        # ==================================================
        # ถ้ายกเลิกการยืม
        # เปลี่ยนสถานะ loan และ loan_units
        # ==================================================

        if transaction["transaction_type"] == "ยืม":

            if transaction["loan_id"] is not None:

                conn.execute("""
                    UPDATE external_loans
                    SET
                        status = 'ยกเลิก',
                        return_date = ?
                    WHERE id = ?
                """, (
                    now(),
                    transaction["loan_id"]
                ))

                conn.execute("""
                    UPDATE loan_units
                    SET
                        status = 'ยกเลิก',
                        return_date = ?
                    WHERE loan_id = ?
                    AND status = 'ยังไม่คืน'
                """, (
                    now(),
                    transaction["loan_id"]
                ))

        # ==================================================
        # ทำเครื่องหมายรายการเดิม
        # ==================================================

        conn.execute("""
            UPDATE transactions
            SET cancelled = 1
            WHERE id = ?
        """, (
            transaction_id,
        ))

        # ==================================================
        # สร้างประวัติการยกเลิก
        # ==================================================

        conn.execute("""
            INSERT INTO transactions
            (
                requester,
                drug_id,
                quantity,
                transaction_type,
                transaction_date,
                cancelled,
                loan_id,
                box_loan_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            transaction["requester"],
            transaction["drug_id"],
            transaction["quantity"],
            "ยกเลิก",
            now(),
            0,
            transaction["loan_id"],
            None
        ))

        conn.commit()
        conn.close()

        flash(
            f"✅ ยกเลิกรายการ "
            f"{transaction['drug_name']} "
            f"{transaction['quantity']:g} "
            f"{transaction['drug_unit']} แล้ว"
        )

        return redirect(
            url_for("report")
        )

    except Exception as e:

        conn.rollback()

        print(
            "CANCEL ERROR:",
            e
        )

        conn.close()

        flash(
            "❌ ไม่สามารถยกเลิกรายการได้"
        )

        return redirect(
            url_for("report")
        )


# ==================================================
# รีเซ็ตทั้งหมด
# ==================================================

@app.route("/reset-all", methods=["POST"])
def reset_all():

    conn = get_db()

    try:

        conn.execute("""
            DELETE FROM loan_units
        """)

        conn.execute("""
            DELETE FROM transactions
        """)

        conn.execute("""
            DELETE FROM external_loans
        """)

        conn.execute("""
            DELETE FROM box_unit_items
        """)

        conn.execute("""
            DELETE FROM box_units
        """)

        conn.execute("""
            DELETE FROM box_items
        """)

        conn.execute("""
            DELETE FROM box_loans
        """)

        conn.execute("""
            DELETE FROM drugs
        """)

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "RESET ERROR:",
            e
        )

        flash(
            "❌ ไม่สามารถรีเซ็ตข้อมูลได้"
        )

        conn.close()

        return redirect(
            url_for("stock")
        )

    conn.close()

    flash(
        "🗑️ รีเซ็ตข้อมูลทั้งหมดเรียบร้อยแล้ว"
    )

    return redirect(
        url_for("stock")
    )


# ==================================================
# เริ่มระบบ
# ==================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )