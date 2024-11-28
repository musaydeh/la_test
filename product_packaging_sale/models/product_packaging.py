# -*- coding: utf-8 -*-

from odoo import models, fields


class StockPackageType(models.Model):
    _inherit = "stock.package.type"

    packaging_product_id = fields.Many2one("product.product", string="Packaging Product")


class ProductPackaging(models.Model):
    _inherit = "product.packaging"

    packaging_product_id = fields.Many2one(related="package_type_id.packaging_product_id", string="Packaging Product",
                                           readonly=True, store=True)
