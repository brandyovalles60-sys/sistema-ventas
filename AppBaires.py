import streamlit as st
import os
import json
import psycopg2
import pdfplumber
import re
from datetime import datetime


def extraer_total(pdf_path):
    total_encontrado = 0

    with pdfplumber.open(pdf_path) as pdf:
        texto_completo = ""

        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                texto_completo += texto + "\n"

    # Buscar palabra TOTAL seguida de número
    patron = r"TOTAL\s*\$?\s*([\d,]+\.\d{2})"
    coincidencia = re.search(patron, texto_completo, re.IGNORECASE)

    if coincidencia:
        total = coincidencia.group(1)
        total = total.replace(",", "")
        total_encontrado = float(total)

    return total_encontrado

st.set_page_config(page_title="Sistema de Ventas", layout="wide")

# ==============================
# CREAR CARPETA PDF
# ==============================
if not os.path.exists("pdfs"):
    os.makedirs("pdfs")

# ==============================
# BASE DE DATOS
# ==============================
DATABASE_URL = st.secrets["DATABASE_URL"]

conn = psycopg2.connect(DATABASE_URL)
c = conn.cursor()



# ==============================
# LISTA FIJA DE VINOS
# ==============================
vinos = [
    "Royal Cabernet",
    "Descarriados",
    "Royal Malbec",
    "Aureo Chardonnay",
    "Aureo ruta 90",
    "Petit verdot",
    "Callejon comunero",
    "Espumoso FincaBV"
]

# Asegurar que todos los vinos existan en almacén
for vino in vinos:
    c.execute("SELECT vino FROM almacen WHERE vino = %s", (vino,))
    existe = c.fetchone()
    if not existe:
        c.execute("INSERT INTO almacen (vino, cantidad) VALUES (%s, %s)", (vino, 0))

conn.commit()

# ==============================
# MENÚ
# ==============================
menu = st.sidebar.selectbox("Menú", [
    "Registrar Cliente",
    "Almacén",
    "Registrar Venta",
    "Historial"
])

# ==============================
# REGISTRAR CLIENTE
# ==============================
if menu == "Registrar Cliente":
    st.title("👤 Registrar Cliente")

    nombre = st.text_input("Nombre del Cliente")
    numero = st.text_input("Número")
    rnc = st.text_input("RNC")
    representante = st.text_input("Representante")

    if st.button("Guardar Cliente"):
        if nombre.strip() != "":
            c.execute("""
            INSERT INTO clientes (nombre, numero, rnc, representante)
            VALUES (%s, %s, %s, %s)
            """, (nombre.strip(), numero.strip(), rnc.strip(), representante.strip()))
            conn.commit()
            st.success("Cliente registrado")

    st.divider()
    st.subheader("Clientes Registrados")

    c.execute("SELECT * FROM clientes")
    clientes = c.fetchall()

    for cliente in clientes:
        col1, col2 = st.columns([5,1])
        col1.write(f"{cliente[1]} | Número: {cliente[2]} | RNC: {cliente[3]} | Rep: {cliente[4]}")
        if col2.button("Eliminar", key=f"del{cliente[0]}"):
            c.execute("DELETE FROM clientes WHERE id=%s", (cliente[0],))
            c.execute("DELETE FROM ventas WHERE cliente_id=%s", (cliente[0],))
            conn.commit()
            st.rerun()

# ==============================
# ALMACÉN
# ==============================
elif menu == "Almacén":
    st.title("📦 Control de Almacén")

    c.execute("SELECT vino, cantidad FROM almacen ORDER BY vino")
    inventario = c.fetchall()

    for vino, cantidad in inventario:
        col1, col2, col3 = st.columns([3,1,1])
        col1.write(f"**{vino}**")
        col2.write(f"Stock: {cantidad}")

        agregar = col3.number_input(
            f"Agregar {vino}",
            min_value=0,
            step=1,
            key=f"add{vino}"
        )

        if st.button(f"Actualizar {vino}", key=f"btn{vino}"):
            c.execute("UPDATE almacen SET cantidad = cantidad + %s WHERE vino = %s", (agregar, vino))
            conn.commit()
            st.rerun()

# ==============================
# REGISTRAR VENTA
# ==============================
elif menu == "Registrar Venta":
    st.title("🛒 Registrar Venta")

    c.execute("SELECT id, nombre FROM clientes")
    clientes = c.fetchall()
    cliente_dict = {nombre: id for id, nombre in clientes}

    if not cliente_dict:
        st.warning("Primero registra un cliente.")
    else:
        cliente_nombre = st.selectbox("Seleccionar Cliente", list(cliente_dict.keys()))
        cliente_id = cliente_dict[cliente_nombre]

        productos = []
        c.execute("SELECT vino, cantidad FROM almacen ORDER BY vino")
        inventario = c.fetchall()

        st.subheader("Seleccionar Productos")

        for vino, stock in inventario:
            cantidad = st.number_input(
                f"{vino} (Disponible: {stock})",
                min_value=0,
                max_value=stock,
                step=1,
                key=f"venta{vino}"
            )

            if cantidad > 0:
                productos.append({
                    "vino": vino,
                    "cantidad": cantidad
                })

        factura = st.file_uploader("Subir PDF Factura", type=["pdf"])
        consignacion = st.file_uploader("Subir PDF Consignación", type=["pdf"])

        if st.button("Guardar Venta"):
            if productos:
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                productos_json = json.dumps(productos)

                factura_path = ""
                consignacion_path = ""

                if factura:
                    factura_path = f"pdfs/factura_{datetime.now().timestamp()}.pdf"
                    with open(factura_path, "wb") as f:
                        f.write(factura.read())

                if consignacion:
                    consignacion_path = f"pdfs/consignacion_{datetime.now().timestamp()}.pdf"
                    with open(consignacion_path, "wb") as f:
                        f.write(consignacion.read())

                monto_venta = 0
                if factura_path:
                    monto_venta = extraer_total(factura_path)
                else:
                    st.warning("No se detectó factura. Monto no agregado automáticamente.")

                st.write("Monto detectado:", monto_venta)

                c.execute("""
                INSERT INTO ventas (cliente_id, productos, fecha, pdf_factura, pdf_consignacion)
                VALUES (%s, %s, %s, %s, %s)
                """, (cliente_id, productos_json, fecha, factura_path, consignacion_path))
                
                
                c.execute("""
                INSERT INTO cuentas_por_cobrar (cliente_id, monto_total)
                VALUES (%s, %s)
                ON CONFLICT (cliente_id)
                DO UPDATE SET monto_total = cuentas_por_cobrar.monto_total + EXCLUDED.monto_total
                """, (cliente_id, monto_venta))

                for item in productos:
                    c.execute("""
                    UPDATE almacen
                    SET cantidad = cantidad - %s
                    WHERE vino = %s
                    """, (item["cantidad"], item["vino"]))

                conn.commit()
                st.success("Venta registrada correctamente")
                st.rerun()
            else:
                st.warning("Selecciona al menos un producto.")

# ==============================
# HISTORIAL
# ==============================
elif menu == "Historial":
    st.title("📚 Historial por Cliente")

    buscar = st.text_input("Buscar Cliente")

    if buscar:
        c.execute(
            "SELECT id, nombre FROM clientes WHERE nombre LIKE %s",
            (f"%{buscar}%",)
        )
        clientes = c.fetchall()
    else:
        c.execute("SELECT id, nombre FROM clientes")
        clientes = c.fetchall()

    for cliente_id, nombre in clientes:
        with st.expander(nombre):

            c.execute("""
            SELECT id, productos, fecha, pdf_factura, pdf_consignacion
            FROM ventas
            WHERE cliente_id = %s
            ORDER BY fecha DESC
            """, (cliente_id,))
            ventas = c.fetchall()

            if not ventas:
                st.write("Sin ventas.")
            else:
                for venta in ventas:
                    st.write(f"Fecha: {venta[2]}")

                    try:
                        productos = json.loads(venta[1]) if venta[1] else []
                    except:
                        productos = []

                    for item in productos:
                        st.write(f"- {item['vino']} | Cantidad: {item['cantidad']}")

                    if venta[3] and os.path.exists(venta[3]):
                        with open(venta[3], "rb") as f:
                            st.download_button(
                                "Descargar Factura",
                                f,
                                file_name="factura.pdf",
                                key=f"f{venta[0]}"
                            )

                    if venta[4] and os.path.exists(venta[4]):
                        with open(venta[4], "rb") as f:
                            st.download_button(
                                "Descargar Consignación",
                                f,
                                file_name="consignacion.pdf",
                                key=f"c{venta[0]}"
                            )


                    st.divider()











