from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    sunat_mode = fields.Selection(
        [
            ("beta", "Beta"),
            ("prod", "Producción"),
        ],
        string="Modo SUNAT",
        default="beta",
    )
    sunat_serie_factura = fields.Char(string="Serie Factura SUNAT")
    sunat_serie_boleta = fields.Char(string="Serie Boleta SUNAT")
    sunat_user = fields.Char(string="Usuario SUNAT")
    sunat_password = fields.Char(string="Clave SUNAT", groups="base.group_system")
    sunat_certificate_path = fields.Char(string="Ruta Certificado")
    sunat_certificate_password = fields.Char(
        string="Clave Certificado", groups="base.group_system"
    )
