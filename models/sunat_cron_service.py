from odoo import models, fields
import pytz


class SunatCronService(models.AbstractModel):
    _name = "sunat.cron.service"
    _description = "Cron SUNAT POS"

    def cron_send_daily_boletas_rc(self):

        orders = self.env["pos.order"].search(
            [
                ("sunat_document_type", "=", "03"),
                ("sunat_state", "in", ["boleta", "pendiente_resumen"]),
                ("sunat_excluir_resumen", "!=", True),
                ("venta_anulada", "!=", True),
                ("es_reversa_anulacion", "!=", True),
                ("sunat_rc_batch_id", "=", False),
            ]
        )

        if not orders:
            return True

        grupos = {}

        tz_pe = pytz.timezone("America/Lima")

        for order in orders:
            dt = fields.Datetime.to_datetime(order.date_order)

            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)

            fecha_peru = dt.astimezone(tz_pe).date()

            key = (order.config_id.id, fecha_peru)

            grupos.setdefault(key, self.env["pos.order"])
            grupos[key] |= order

        for (config_id, fecha_peru), orders_group in sorted(
            grupos.items(), key=lambda x: x[0][1]
        ):
            batch = self.env["sunat.summary.batch"].create(
                {
                    "date": fecha_peru,
                }
            )

            batch.order_ids = [(6, 0, orders_group.ids)]

            batch.action_send_summary()

        return True

    def cron_check_pending_tickets(self):
        self.env["sunat.summary.batch"].cron_retry_pending_summaries()
        return True

    def cron_retry_pending_invoices(self):

        # ============================================================
        # 1. FACTURAS CON RESPUESTA INCIERTA
        # Primero consultar SUNAT. Nunca reenviar directamente.
        # ============================================================
        invoices_to_verify = self.env["pos.order"].search(
            [
                ("sunat_document_type", "=", "01"),
                ("sunat_state", "=", "pendiente_verificacion"),
            ]
        )

        if invoices_to_verify:
            invoices_to_verify.action_verify_sunat_invoice()

        # ============================================================
        # 2. FACTURAS QUE SUNAT CONFIRMÓ QUE NO EXISTEN
        # Recién estas quedan autorizadas para reintento.
        # ============================================================
        invoices_to_send = self.env["pos.order"].search(
            [
                ("sunat_document_type", "=", "01"),
                ("sunat_state", "=", "pendiente_envio"),
            ]
        )

        for order in invoices_to_send:
            order.action_send_sunat()

        return True
