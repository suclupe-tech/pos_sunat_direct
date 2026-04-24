from odoo import fields, models
from odoo.exceptions import UserError
from cryptography.hazmat.primitives.serialization import pkcs12


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

    class PosConfig(models.Model):
        _inherit = "pos.config"

    # (dejas tus campos como están)

    def action_test_certificate(self):
        self.ensure_one()

        if not self.sunat_certificate_path:
            raise UserError("Falta ruta del certificado.")

        if not self.sunat_certificate_password:
            raise UserError("Falta clave del certificado.")

        try:
            with open(self.sunat_certificate_path, "rb") as cert_file:
                pfx_data = cert_file.read()

            private_key, certificate, extra = pkcs12.load_key_and_certificates(
                pfx_data,
                self.sunat_certificate_password.encode(),
            )

            if not private_key or not certificate:
                raise UserError(
                    "Certificado cargó pero no contiene llave privada válida."
                )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "SUNAT",
                    "message": "Certificado válido y leído correctamente.",
                    "type": "success",
                    "sticky": False,
                },
            }

        except Exception as e:
            raise UserError(f"Error leyendo certificado:\n{str(e)}")
