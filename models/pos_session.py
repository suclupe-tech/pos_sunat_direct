from odoo import models, fields


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_liquidacion_data(self):
        self.ensure_one()

        orders = self.order_ids.filtered(lambda o: o.state in ["paid", "done"])
        saldo_inicial = getattr(self, "cash_register_balance_start", 0.0) or 0.0

        def safe_name(order):
            return (
                (order.partner_id.name or "").strip().lower()
                if order.partner_id
                else ""
            )

        def has_ruc(order):
            return (
                order.partner_id
                and order.partner_id.vat
                and str(order.partner_id.vat).strip().isdigit()
                and len(str(order.partner_id.vat).strip()) == 11
            )

        def is_cliente_generico(order):
            return safe_name(order) in [
                "cliente varios",
                "varios",
                "consumidor final",
                "cliente final",
            ]

        def is_factura(order):
            if getattr(order, "sunat_document_type", False) == "01":
                return True
            return has_ruc(order)

        def is_boleta(order):
            if getattr(order, "sunat_document_type", False) == "03":
                return True
            return bool(
                order.partner_id
                and not has_ruc(order)
                and not is_cliente_generico(order)
            )

        def is_nota_venta(order):
            return not is_factura(order) and not is_boleta(order)

        def es_efectivo(payment):
            nombre = (payment.payment_method_id.name or "").strip().lower()
            return "efectivo" in nombre or "cash" in nombre

        # =========================
        # VENTAS POR TIPO Y MEDIO
        # =========================
        facturas_efectivo = 0.0
        facturas_no_efectivo = 0.0

        boletas_efectivo = 0.0
        boletas_no_efectivo = 0.0

        nota_venta_efectivo = 0.0
        nota_venta_no_efectivo = 0.0

        for order in orders:
            if is_factura(order):
                tipo_doc = "factura"
            elif is_boleta(order):
                tipo_doc = "boleta"
            else:
                tipo_doc = "nota"

            for pay in order.payment_ids:
                monto = pay.amount or 0.0

                if es_efectivo(pay):
                    if tipo_doc == "factura":
                        facturas_efectivo += monto
                    elif tipo_doc == "boleta":
                        boletas_efectivo += monto
                    else:
                        nota_venta_efectivo += monto
                else:
                    if tipo_doc == "factura":
                        facturas_no_efectivo += monto
                    elif tipo_doc == "boleta":
                        boletas_no_efectivo += monto
                    else:
                        nota_venta_no_efectivo += monto

        total_facturas = facturas_efectivo + facturas_no_efectivo
        total_boletas = boletas_efectivo + boletas_no_efectivo
        total_nota_venta = nota_venta_efectivo + nota_venta_no_efectivo

        total_ventas_efectivo = (
            facturas_efectivo + boletas_efectivo + nota_venta_efectivo
        )
        total_ventas_no_efectivo = (
            facturas_no_efectivo + boletas_no_efectivo + nota_venta_no_efectivo
        )

        total_ventas = total_ventas_efectivo + total_ventas_no_efectivo

        # =========================
        # MOVIMIENTOS DE CAJA
        # =========================
        cash_moves = self.statement_ids.line_ids.filtered(
            lambda l: l.amount and l.amount != 0
        )

        def move_es_efectivo(line):
            nombre = (line.payment_ref or line.ref or "").strip().lower()
            # Ajusta esta lógica si en tus movimientos usas otros nombres
            return not any(
                x in nombre
                for x in ["yape", "plin", "transferencia", "tarjeta", "cuenta"]
            )

        ingresos_adicionales_efectivo = [
            {
                "name": line.payment_ref or line.ref or "Ingreso efectivo",
                "amount": line.amount,
            }
            for line in cash_moves
            if line.amount > 0 and move_es_efectivo(line)
        ]
        total_ingresos_adicionales_efectivo = sum(
            x["amount"] for x in ingresos_adicionales_efectivo
        )

        ingresos_adicionales_no_efectivo = [
            {
                "name": line.payment_ref or line.ref or "Ingreso no efectivo",
                "amount": line.amount,
            }
            for line in cash_moves
            if line.amount > 0 and not move_es_efectivo(line)
        ]
        total_ingresos_adicionales_no_efectivo = sum(
            x["amount"] for x in ingresos_adicionales_no_efectivo
        )

        egresos_efectivo = [
            {
                "name": line.payment_ref or line.ref or "Egreso efectivo",
                "amount": abs(line.amount),
            }
            for line in cash_moves
            if line.amount < 0 and move_es_efectivo(line)
        ]
        total_egresos_efectivo = sum(x["amount"] for x in egresos_efectivo)

        egresos_no_efectivo = [
            {
                "name": line.payment_ref or line.ref or "Egreso no efectivo",
                "amount": abs(line.amount),
            }
            for line in cash_moves
            if line.amount < 0 and not move_es_efectivo(line)
        ]
        total_egresos_no_efectivo = sum(x["amount"] for x in egresos_no_efectivo)

        total_egresos = total_egresos_efectivo + total_egresos_no_efectivo

        # =========================
        # TOTALES REALES
        # =========================
        total_ingreso = (
            saldo_inicial + total_ventas_efectivo + total_ingresos_adicionales_efectivo
        )

        saldo_en_caja = total_ingreso - total_egresos_efectivo

        return {
            "fecha": fields.Date.context_today(self).strftime("%d/%m/%Y"),
            "hora": fields.Datetime.now().strftime("%H:%M:%S"),
            "saldoAnterior": saldo_inicial,
            # Ventas por tipo
            "totalFacturas": total_facturas,
            "totalBoletas": total_boletas,
            "totalNotaVenta": total_nota_venta,
            # Ventas por tipo y medio
            "facturasEfectivo": facturas_efectivo,
            "facturasNoEfectivo": facturas_no_efectivo,
            "boletasEfectivo": boletas_efectivo,
            "boletasNoEfectivo": boletas_no_efectivo,
            "notaVentaEfectivo": nota_venta_efectivo,
            "notaVentaNoEfectivo": nota_venta_no_efectivo,
            # Totales ventas
            "totalVentasEfectivo": total_ventas_efectivo,
            "totalVentasNoEfectivo": total_ventas_no_efectivo,
            "totalVentas": total_ventas,
            # Otros ingresos
            "ingresosAdicionalesEfectivo": ingresos_adicionales_efectivo,
            "totalIngresosAdicionalesEfectivo": total_ingresos_adicionales_efectivo,
            "ingresosAdicionalesNoEfectivo": ingresos_adicionales_no_efectivo,
            "totalIngresosAdicionalesNoEfectivo": total_ingresos_adicionales_no_efectivo,
            # Egresos
            "egresosEfectivo": egresos_efectivo,
            "totalEgresosEfectivo": total_egresos_efectivo,
            "egresosNoEfectivo": egresos_no_efectivo,
            "totalEgresosNoEfectivo": total_egresos_no_efectivo,
            "totalEgresos": total_egresos,
            # Totales caja
            "totalIngreso": total_ingreso,
            "saldoEnCaja": saldo_en_caja,
        }


