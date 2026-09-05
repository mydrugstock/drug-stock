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
# วันที่ปัจจุบัน
# ==================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


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
    conn.close()

    flash(
        f"✅ เพิ่ม {name} "
        f"จำนวน {quantity:g} {unit} "
        f"เข้าสต๊อกแล้ว"
    )

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

    conn = get_db()

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
            "❌ ไม่พบยาที่เลือก"
        )

        return redirect(
            url_for("borrow")
        )

    if quantity <= 0:

        conn.close()

        flash(
            "❌ จำนวนต้องมากกว่า 0"
        )

        return redirect(
            url_for("borrow")
        )

    if quantity > drug["quantity"]:

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
            f"{quantity:g} {drug['unit']} สำเร็จ"
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

    conn.close()

    flash(
        "❌ ไม่พบประเภทการทำรายการ"
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

    # ==================================================
    # รายการยา
    # ==================================================

    drugs = conn.execute("""
        SELECT *
        FROM drugs
        ORDER BY name
    """).fetchall()

    # ==================================================
    # สูตรกล่อง
    # ==================================================

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

    # ==================================================
    # ชุดกล่องที่ยังมีของรอคืน
    # ==================================================

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

    # ==================================================
    # กล่องแต่ละใบที่รอคืน
    # ==================================================

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

    # ==================================================
    # ห้ามเปลี่ยนสูตรขณะมีกล่องรอคืน
    # ==================================================

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

    # ==================================================
    # ตรวจสอบสต๊อก
    # ==================================================

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

    # ==================================================
    # สร้างชุดการยืม
    # ==================================================

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

    # ==================================================
    # สร้างกล่องที่ 1
    # ==================================================

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

    # ==================================================
    # หักยาออกจากสต๊อก
    # ==================================================

    for item in box_items:

        conn.execute("""
            UPDATE drugs
            SET quantity = quantity - ?
            WHERE id = ?
        """, (
            item["quantity_per_box"],
            item["drug_id"]
        ))

        # ==================================================
        # บันทึกยาในกล่อง
        # ==================================================

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

        # ==================================================
        # ประวัติ
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

    # ==================================================
    # ตรวจสอบสต๊อกทั้งหมดก่อน
    # ==================================================

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

    # ==================================================
    # หาเลขกล่องล่าสุด
    # ==================================================

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

    # ==================================================
    # สร้างกล่องทีละใบ
    # ==================================================

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

        # ==================================================
        # หักยา
        # ==================================================

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

            # ==================================================
            # บันทึกยาในกล่อง
            # ==================================================

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

            # ==================================================
            # ประวัติ
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
                box_loan["borrower"],
                item["drug_id"],
                required,
                "เพิ่มกล่อง",
                transaction_date,
                0,
                None,
                box_loan_id
            ))

    # ==================================================
    # เพิ่มจำนวนกล่อง
    # ==================================================

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

    # ==================================================
    # ดึงข้อมูลกล่อง + ชื่อผู้ยืม
    # ==================================================

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

    # ==================================================
    # ดึงยาในกล่อง
    # ==================================================

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

    # ==================================================
    # ตรวจสอบ box_unit_id
    # ==================================================

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

    # ==================================================
    # ดึงข้อมูลกล่อง + ผู้ยืม
    # ==================================================

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

    # ==================================================
    # ดึงยาในกล่อง
    # ==================================================

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

    # ==================================================
    # อ่านจำนวนยาที่เหลือจริง
    # ==================================================

    return_data = []

    for item in items:

        field_name = (
            f"remaining_{item['id']}"
        )

        value = request.form.get(
            field_name
        )

        if value is None or value.strip() == "":

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

        # ==================================================
        # ตรวจจำนวนติดลบ
        # ==================================================

        if remaining < 0:

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

        # ==================================================
        # ตรวจว่ามากกว่าตอนยืมหรือไม่
        # ==================================================

        if remaining > item["original_quantity"]:

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

        # ==================================================
        # คำนวณจำนวนใช้ไป
        # ==================================================

        used = (
            item["original_quantity"]
            - remaining
        )

        # ==================================================
        # จำนวนที่นำกลับเข้าสต๊อก
        # ==================================================

        returned = remaining

        return_data.append({
            "item": item,
            "remaining": remaining,
            "used": used,
            "returned": returned
        })

    transaction_date = now()

    # ==================================================
    # คืนยาเข้าสต๊อก
    # ==================================================

    for data in return_data:

        item = data["item"]

        remaining = data["remaining"]

        used = data["used"]

        returned = data["returned"]

        # ==================================================
        # เพิ่มยาที่เหลือกลับเข้าสต๊อก
        # ==================================================

        conn.execute("""
            UPDATE drugs
            SET quantity = quantity + ?
            WHERE id = ?
        """, (
            returned,
            item["drug_id"]
        ))

        # ==================================================
        # บันทึกผลของยาในกล่อง
        # ==================================================

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

        # ==================================================
        # บันทึกประวัติ
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
            box_unit["borrower"],
            item["drug_id"],
            returned,
            "คืนกล่อง",
            transaction_date,
            0,
            None,
            box_unit["box_loan_id"]
        ))

    # ==================================================
    # เปลี่ยนสถานะกล่องเป็น "คืนแล้ว"
    # ==================================================

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

    # ==================================================
    # ตรวจจำนวนกล่องทั้งหมด
    # ==================================================

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

    # ==================================================
    # ถ้าคืนครบทุกกล่อง
    # ==================================================

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

    # ==================================================
    # บันทึกฐานข้อมูล
    # ==================================================

    conn.commit()

    conn.close()

    # ==================================================
    # แจ้งผล
    # ==================================================

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

        remaining_percent = float(
            request.form["remaining_percent"]
        )

    except (ValueError, KeyError):

        flash(
            "❌ ข้อมูลการคืนยาไม่ถูกต้อง"
        )

        return redirect(
            url_for("return_drug")
        )

    if remaining_percent < 0:

        flash(
            "❌ เปอร์เซ็นต์ต้องไม่ต่ำกว่า 0%"
        )

        return redirect(
            url_for("return_drug")
        )

    if remaining_percent > 100:

        flash(
            "❌ เปอร์เซ็นต์ต้องไม่เกิน 100%"
        )

        return redirect(
            url_for("return_drug")
        )

    conn = get_db()

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
    """, (
        loan_id,
    )).fetchone()

    if loan is None:

        conn.close()

        flash(
            "❌ ไม่พบรายการยืม"
        )

        return redirect(
            url_for("return_drug")
        )

    # ==================================================
    # คำนวณ
    # ==================================================

    used_percent = (
        100 - remaining_percent
    )

    used_quantity = (
        loan["quantity"]
        * used_percent
        / 100
    )

    returned_quantity = (
        loan["quantity"]
        * remaining_percent
        / 100
    )

    new_stock = (
        loan["stock_quantity"]
        + returned_quantity
    )

    # ==================================================
    # เพิ่มยากลับเข้าสต๊อก
    # ==================================================

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
    # เปลี่ยนสถานะการยืม
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
        remaining_percent,
        used_quantity,
        return_date,
        loan_id
    ))

    # ==================================================
    # บันทึกประวัติ
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
        "คืน",
        return_date,
        0,
        loan_id,
        None
    ))

    conn.commit()
    conn.close()

    flash(
        f"✅ คืนยา {loan['drug_name']} สำเร็จ | "
        f"เหลือ {remaining_percent:g}% | "
        f"ใช้ไป {used_quantity:g} "
        f"{loan['drug_unit']}"
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

    # ==================================================
    # ตรวจว่าถูกยกเลิกไปแล้วหรือยัง
    # ==================================================

    if transaction["cancelled"] == 1:

        conn.close()

        flash(
            "⚠️ รายการนี้ถูกยกเลิกแล้ว"
        )

        return redirect(
            url_for("report")
        )

    # ==================================================
    # รายการคืนยกเลิกไม่ได้
    # ==================================================

    if transaction["transaction_type"] in (
        "คืน",
        "คืนกล่อง"
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
    # ยืมภายนอก
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

    # ==================================================
    # คืนยาเข้าสต๊อก
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
    # ยกเลิก loan
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

    # ==================================================
    # ทำเครื่องหมายยกเลิก
    # ==================================================

    conn.execute("""
        UPDATE transactions
        SET cancelled = 1
        WHERE id = ?
    """, (
        transaction_id,
    ))

    # ==================================================
    # บันทึกประวัติยกเลิก
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


# ==================================================
# รีเซ็ตทั้งหมด
# ==================================================

@app.route("/reset-all", methods=["POST"])
def reset_all():

    conn = get_db()

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