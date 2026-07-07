from odoo import models, fields


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_liquidacion_data(self):
        self.ensure_one()

        orders_ventas = self.order_ids.filtered(
            lambda o: o.state in ["paid", "done"]
            and not getattr(o, "es_reversa_anulacion", False)
        )

        orders_caja = self.order_ids.filtered(lambda o: o.state in ["paid", "done"])
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

        for order in orders_ventas:
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
        # CAJA REAL POR MEDIO DE PAGO
        # Incluye ventas normales y reversas/anulaciones
        # =========================
        total_caja_efectivo = 0.0
        total_caja_no_efectivo = 0.0

        total_anulaciones_efectivo = 0.0
        total_anulaciones_no_efectivo = 0.0

        medios_pago_no_efectivo_dict = {}

        for order in orders_caja:
            es_reversa = getattr(order, "es_reversa_anulacion", False)

            for pay in order.payment_ids:
                monto = pay.amount or 0.0

                if es_efectivo(pay):
                    total_caja_efectivo += monto

                    if es_reversa or monto < 0:
                        total_anulaciones_efectivo += abs(monto)
                else:
                    total_caja_no_efectivo += monto

                    nombre_medio = pay.payment_method_id.name or "Sin método"

                    if nombre_medio not in medios_pago_no_efectivo_dict:
                        medios_pago_no_efectivo_dict[nombre_medio] = 0.0

                    medios_pago_no_efectivo_dict[nombre_medio] += monto

                    if es_reversa or monto < 0:
                        total_anulaciones_no_efectivo += abs(monto)

        total_caja_real = total_caja_efectivo + total_caja_no_efectivo
        total_anulaciones = total_anulaciones_efectivo + total_anulaciones_no_efectivo

        medios_pago_no_efectivo = [
            {
                "name": name,
                "amount": amount,
                "detalle": "",
            }
            for name, amount in medios_pago_no_efectivo_dict.items()
        ]

        # =========================
        # MOVIMIENTOS DE CAJA
        # Compatible con Odoo 19
        # =========================
        if "statement_line_ids" in self._fields:
            cash_moves = self.statement_line_ids.filtered(
                lambda l: l.amount and l.amount != 0
            )
        elif "pos_session_id" in self.env["account.bank.statement.line"]._fields:
            cash_moves = self.env["account.bank.statement.line"].search(
                [
                    ("pos_session_id", "=", self.id),
                    ("amount", "!=", 0),
                ]
            )
        else:
            cash_moves = self.env["account.bank.statement.line"]

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
            saldo_inicial + total_caja_efectivo + total_ingresos_adicionales_efectivo
        )

        saldo_en_caja = total_ingreso - total_egresos_efectivo

        # =========================
        # FECHA Y HORA DEL REPORTE
        # Si la sesión ya cerró, usa la fecha/hora de cierre.
        # Si aún está abierta, usa la fecha/hora actual.
        # =========================
        fecha_base = (
            self.stop_at or self.write_date or self.start_at or fields.Datetime.now()
        )

        fecha_base_local = fields.Datetime.context_timestamp(self, fecha_base)

        hora_apertura = "-"
        if self.start_at:
            hora_apertura = fields.Datetime.context_timestamp(
                self, self.start_at
            ).strftime("%H:%M:%S")

        hora_cierre = "-"
        if self.stop_at:
            hora_cierre = fields.Datetime.context_timestamp(
                self, self.stop_at
            ).strftime("%H:%M:%S")

        return {
            "fecha": fecha_base_local.strftime("%d/%m/%Y"),
            "hora": fecha_base_local.strftime("%H:%M:%S"),
            "horaApertura": hora_apertura,
            "horaCierre": hora_cierre,
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
            # Caja real con anulaciones
            "totalCajaEfectivo": total_caja_efectivo,
            "totalCajaNoEfectivo": total_caja_no_efectivo,
            "totalCajaReal": total_caja_real,
            "totalAnulacionesEfectivo": total_anulaciones_efectivo,
            "totalAnulacionesNoEfectivo": total_anulaciones_no_efectivo,
            "totalAnulaciones": total_anulaciones,
            "mediosPagoNoEfectivo": medios_pago_no_efectivo,
            "totalMediosPagoNoEfectivo": total_caja_no_efectivo,
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
