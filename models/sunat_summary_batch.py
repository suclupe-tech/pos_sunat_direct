from odoo import models, fields


class SunatSummaryBatch(models.Model):
    _name = "sunat.summary.batch"
    _description = "Resumen Diario SUNAT RC"

    name = fields.Char(string="Nombre RC", readonly=True)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True)

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("generated", "Generado"),
            ("sent", "Enviado"),
            ("accepted", "Aceptado"),
            ("error", "Error"),
        ],
        string="Estado",
        default="draft",
        readonly=True,
    )

    order_ids = fields.Many2many(
        "pos.order",
        string="Boletas incluidas",
    )

    xml_file = fields.Binary(string="Archivo XML", readonly=True)
    xml_filename = fields.Char(string="Nombre XML", readonly=True)

    zip_file = fields.Binary(string="Archivo ZIP", readonly=True)
    zip_filename = fields.Char(string="Nombre ZIP", readonly=True)

    ticket = fields.Char(string="Ticket SUNAT", readonly=True)
    response_message = fields.Text(string="Respuesta SUNAT", readonly=True)

    def action_load_pending_boletas(self):
        orders = self.env["pos.order"].search([], limit=10)

        self.order_ids = [(6,0,orders.ids)]

        return True