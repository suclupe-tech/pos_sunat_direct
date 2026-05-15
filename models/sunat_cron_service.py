from odoo import models, fields


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
            ]
        )

        if not orders:
            return True

        for config in orders.mapped("config_id"):
            orders_config = orders.filtered(lambda o: o.config_id == config)

            batch = self.env["sunat.summary.batch"].create(
                {
                    "date": fields.Date.context_today(self),
                }
            )

            batch.order_ids = [(6, 0, orders_config.ids)]

            batch.action_send_summary()

        return True

    def cron_check_pending_tickets(self):

        batches = self.env["sunat.summary.batch"].search(
            [
                ("state", "=", "sent"),
                ("ticket", "!=", False),
            ]
        )

        if not batches:
            return True

        batches.action_check_ticket()

        return True
