import os
import sys

# ==========================================================
# LIBRERÍAS EXTERNAS DE SUNAT
#
# En el entorno de casa las librerías están en D:\odoo_libs
# y en el servidor/trabajo están en C:\odoo_libs.
#
# Se utiliza automáticamente la primera ruta existente para
# que el mismo código funcione en ambos entornos.
# ==========================================================
RUTAS_ODOO_LIBS = [
    r"D:\odoo_libs",
    r"C:\odoo_libs",
]

for ruta_librerias in RUTAS_ODOO_LIBS:
    if os.path.isdir(ruta_librerias):
        if ruta_librerias not in sys.path:
            sys.path.insert(0, ruta_librerias)
        break

from lxml import etree
from signxml.signer import XMLSigner
from signxml import methods
from cryptography.hazmat.primitives.serialization import (
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
)


class SunatSigner:

    @staticmethod
    def sign_xml(xml_content, certificate_path, certificate_password):
        with open(certificate_path, "rb") as cert_file:
            pfx_data = cert_file.read()

        private_key, certificate, extra = pkcs12.load_key_and_certificates(
            pfx_data,
            certificate_password.encode(),
        )

        key_pem = private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        )

        cert_pem = certificate.public_bytes(Encoding.PEM)

        root = etree.fromstring(xml_content.encode("utf-8"))

        signed_root = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
        ).sign(
            root,
            key=key_pem,
            cert=cert_pem,
        )

        ns = {
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }

        signature = signed_root.find(".//ds:Signature", namespaces=ns)
        extension_content = signed_root.find(".//ext:ExtensionContent", namespaces=ns)

        if signature is not None and extension_content is not None:
            signature.set("Id", "signatureKG")

            signature.getparent().remove(signature)
            extension_content.append(signature)

        return etree.tostring(
            signed_root,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        ).decode("utf-8")
