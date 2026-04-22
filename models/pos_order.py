from odoo import models, fields


class PosOrder(models.Model):
    _inherit = "pos.order"

    sunat_state = fields.Char(string="Estado SUNAT", readonly=True)
    sunat_document_type = fields.Char(string="Tipo Documento SUNAT", readonly=True)
    sunat_document_number = fields.Char(string="Número Documento SUNAT", readonly=True)
    sunat_message = fields.Text(string="Mensaje SUNAT", readonly=True)

    sunat_xml = fields.Text(string="XML SUNAT")
    sunat_xml_filename = fields.Char(string="Nombre XML", readonly=True)
    sunat_xml_file = fields.Binary(string="Archivo XML", readonly=True)

    sunat_zip_filename = fields.Char(string="Nombre ZIP", readonly=True)
    sunat_zip_file = fields.Binary(string="Archivo ZIP", readonly=True)

    sunat_summary_filename = fields.Char(string="Nombre Resumen", readonly=True)
    sunat_summary_file = fields.Binary(string="Archivo Resumen", readonly=True)
    sunat_summary_xml = fields.Text(string="XML Resumen")
    sunat_summary_id = fields.Char(string="ID Resumen", readonly=True)

    def action_generate_sunat_xml(self):
        return True

    def action_send_sunat(self):
        return True

    def action_generate_summary_rc(self):
        return True
