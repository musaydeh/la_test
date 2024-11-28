# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = "sale.order"

    picking_packaging_ids = fields.Many2many("stock.picking", string="Transfers Packaging", copy=False)
    delivery_packaging_count = fields.Integer(compute="_compute_delivery_packaging_count",
                                              string="Delivery Packaging Orders")

    def _compute_delivery_packaging_count(self):
        for order in self:
            order.delivery_packaging_count = len(order.picking_packaging_ids)

    def _prepare_picking_packaging_product(self, moves, picking_type, location_dest_id):
        vals = {
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": location_dest_id,
            "partner_id": self.procurement_group_id.partner_id.id,
            "origin": self.name,
            "scheduled_date": self.date_order,
            "move_type": self.picking_policy,
            "move_ids": moves
        }
        return vals

    def create_picking_packaging_products(self):
        moves = []
        warehouse = self.warehouse_id
        picking_type = warehouse.packaging_product_out_type_id or warehouse.out_type_id

        if picking_type.default_location_dest_id:
            location_dest_id = picking_type.default_location_dest_id.id
        elif self.partner_id.property_stock_customer:
            location_dest_id = self.partner_id.property_stock_customer.id
        else:
            location_dest_id, _ = self.env['stock.warehouse']._get_partner_locations()

        for line in self.order_line.filtered(lambda l: l.product_packaging_id):
            if line.product_packaging_id.packaging_product_id:
                moves.append((0, 0, line._prepare_move_packaging_product(picking_type, location_dest_id)))

        if moves:
            picking = self.env["stock.picking"].create(
                self._prepare_picking_packaging_product(moves, picking_type, location_dest_id))
            picking.action_confirm()

            self.write({"picking_packaging_ids": [(4, picking.id)]})

        return True

    def action_confirm(self):
        for sale_order in self:
            if sale_order.state not in ["draft", "sent"]:
                continue

            super(SaleOrder, sale_order).action_confirm()

            # create delivery for all packaging products
            sale_order.create_picking_packaging_products()

    def _action_cancel(self):
        self.picking_packaging_ids.filtered(lambda p: p.state != "done").action_cancel()

        return super(SaleOrder, self)._action_cancel()

    def action_view_delivery_packaging(self):
        if not self.picking_packaging_ids:
            return

        action = self.sudo().env.ref("stock.action_picking_tree_all")
        result = action.read()[0]
        result["domain"] = [("id", "=", self.picking_packaging_ids.ids)]
        return result


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    extra_price = fields.Float(compute="_compute_extra_price", string="Extra Price",
                               digits="Product Price", store=True, readonly=False, precompute=True)
    current_extra_price = fields.Float(compute="_compute_current_extra_price", string="Old Extra Price",
                                       digits="Product Price", store=True, readonly=False, precompute=True)
    price_unit_original = fields.Float(compute="_compute_price_unit_original", string="Unit Price (Original)",
                                       digits="Product Price", store=True, readonly=True, precompute=True)

    @api.depends("product_packaging_id", "product_packaging_qty")
    def _compute_extra_price(self):
        for line in self:
            product = line.product_packaging_id.packaging_product_id
            extra_price = 0
            # print("Product", product)
            if product:
                pricelist_price = line._get_pricelist_extra_price(product, 1)
                print("pricelist_price", pricelist_price)

                # if line.order_id.pricelist_id.discount_policy == 'with_discount':
                #     return pricelist_price

                # if not line.pricelist_item_id:
                #     return pricelist_price

                base_price = line._get_pricelist_price_extra_before_discount(product, 1)
                print("base_price", base_price)

                extra_price = max(base_price, pricelist_price)

            line.extra_price = extra_price

    @api.depends("extra_price")
    def _compute_current_extra_price(self):
        for line in self:
            line.current_extra_price = line.extra_price

    @api.depends("current_extra_price", "price_unit")
    def _compute_price_unit_original(self):
        for line in self:
            if line.current_extra_price == 0:
                line.price_unit_original = line.price_unit

    @api.depends("extra_price", "price_unit_original")
    def _compute_price_unit(self):
        super(SaleOrderLine, self)._compute_price_unit()

        for line in self:
            line.price_unit = ((line.product_uom_qty * line.price_unit_original) + (
                    line.product_packaging_qty * line.extra_price)) / line.product_uom_qty

    def _get_pricelist_extra_price(self, product, qty):
        self.ensure_one()
        order_date = self.order_id.date_order or fields.Date.today()
        qty = qty or 1.0
        uom = product.uom_id
        pricelist_rule_id = self.order_id.pricelist_id._get_product_rule(
            product,
            qty,
            uom=uom,
            date=order_date,
        )
        if not pricelist_rule_id:
            return 0
        pricelist_rule = self.env['product.pricelist.item'].browse(pricelist_rule_id)

        price = pricelist_rule._compute_price(product, qty, uom, order_date,
                                              currency=self.order_id.pricelist_id.currency_id)
        return price

    def _get_pricelist_price_extra_before_discount(self, product, qty):
        self.ensure_one()
        order_date = self.order_id.date_order or fields.Date.today()
        qty = qty or 1.0
        uom = product.uom_id
        pricelist_rule_id = self.order_id.pricelist_id._get_product_rule(
            product,
            qty,
            uom=uom,
            date=order_date,
        )
        if not pricelist_rule_id:
            return 0
        pricelist_rule = self.env['product.pricelist.item'].browse(pricelist_rule_id)
        if pricelist_rule:
            pricelist_item = pricelist_rule
            if pricelist_item.pricelist_id.discount_policy == 'without_discount':
                while pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id.discount_policy == 'without_discount':
                    rule_id = pricelist_item.base_pricelist_id._get_product_rule(product, qty, uom=uom, date=order_date)
                    pricelist_item = self.env['product.pricelist.item'].browse(rule_id)

            pricelist_rule = pricelist_item

        price = pricelist_rule._compute_base_price(product, qty, uom, order_date, target_currency=self.currency_id)

        return price

    def _prepare_move_packaging_product(self, picking_type, location_dest_id):
        product = self.product_packaging_id.packaging_product_id
        vals = {
            "product_id": product.id,
            "name": self.product_id.display_name,
            "description_picking": self.product_id.display_name,
            "origin": self.product_id.display_name,
            "product_uom": product.uom_id.id,
            "product_uom_qty": self.product_packaging_qty,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": location_dest_id
        }
        return vals
