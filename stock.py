# -*- encoding: utf-8 -*-
##############################################################################
#    
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields, osv
from openerp import netsvc

#----------------------------------------------------------
# Stock Picking
# this module includes codes from picking_inv_rel module by camp2camp to avoid a dependency
#----------------------------------------------------------
class stock_picking(osv.osv):
    _inherit = "stock.picking"
    _columns = {
        'invoice_ids': fields.many2many('account.invoice', 'picking_invoice_rel', 'picking_id', 'invoice_id', 'Invoices'),
        'client_order_ref'  : fields.related ('sale_id', 'client_order_ref', type="char", relation="sale.order", string="Client Ref", readonly = True ),

    }
    _description = "Picking List"
    
    def init(self, cr):
    # This is a helper to guess "old" Relations between pickings and invoices
        cr.execute("""
            insert into picking_invoice_rel(picking_id,invoice_id) select p.id,i.id from stock_picking p, account_invoice i
            where p.name = split_part(i.origin,':',1) and (p.id,i.id) not in (select picking_id,invoice_id from picking_invoice_rel);
            """)

    def action_invoice_create(self, cr, uid, ids, journal_id=False,
            group=False, type='out_invoice', context=None):
        '''Return ids of created invoices for the pickings'''
        res = super(stock_picking,self).action_invoice_create(cr, uid, ids, journal_id, group, type, context=context)
        #will use stock input account
        #for both receipts and returns to suppliers
        #if this is a direct ship then do not change account at line level as
        #there will be no stock journal created
        
        #if this is for a SO with Create Invoice <> From Picking then don't 
        
        if not res:
            return res 

        purchase_line_obj=self.pool.get('purchase.order.line')
        invoice_line_obj=self.pool.get('account.invoice.line')
        invoice_obj = self.pool.get('account.invoice')
        picking_obj=self.pool.get('stock.picking')
             
        picking_id = res.keys()[0]
        pick_id = picking_obj.browse(cr, uid, picking_id, context = context)
        inv_type = self._alt_get_invoice_type(pick_id)
        if not inv_type:
            inv_type = type
        
        
        invoice_ids = res.values()[0]
        invoice_id = invoice_ids
        if not isinstance(invoice_ids,list):
            invoice_ids = [invoice_ids]
        self.write(cr, uid, picking_id, {'invoice_ids' : [(6,0, invoice_ids )]}, context=context) 
        
        if inv_type == 'in_refund' or inv_type == 'in_invoice':
            for inv in self.pool.get('account.invoice').browse(cr, uid, res.values(), context=context):
                for ol in inv.invoice_line:
                    if ol.product_id:
                        olid = ol.id
                        cr.execute("select order_line_id from purchase_order_line_invoice_rel where invoice_id = %s", (olid,))
                        result = cr.fetchone()
                        if result[0]:
                            cr.execute("select location_dest_id from stock_move where purchase_line_id = %s", (result[0],))
                            location_id = cr.fetchone()
                            if location_id[0]:
                                cr.execute("select usage from stock_location where id = %s", (location_id[0],))
                                usage = cr.fetchone()
                                if usage[0] == 'customer':
                                    continue
                                                
                        oa = ol.product_id.product_tmpl_id.property_stock_account_input and ol.product_id.product_tmpl_id.property_stock_account_input.id
                        if not oa:
                            oa = ol.product_id.categ_id.property_stock_account_input_categ and ol.product_id.categ_id.property_stock_account_input_categ.id        
                        if oa:
                            fpos = ol.invoice_id.fiscal_position or False
                            a = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, oa)
                            self.pool.get('account.invoice.line').write(cr, uid, [ol.id], {'account_id': a})
        
        #this code caters for non-stock items included in a purchase order to be invoiced from the picking as these lines do not have a move so are ignored by invoice_create
        #need to find the lines, check that they have not already been invoiced and add to the invoice
        #exclude in_refund as assume service costs not creditable automatically
        
        if inv_type == 'in_invoice':
            pick_ids = picking_obj.browse(cr, uid, picking_id, context = context)
            purchase_ids = pick_ids.purchase_id.id
            po_lines = purchase_line_obj.search(cr, uid, [('order_id', 'in', [purchase_ids])], context=context)  
            for po_line in po_lines:
                po_line=purchase_line_obj.browse(cr, uid, po_line, context=context)
                if po_line.product_id.product_tmpl_id.type == 'service' and po_line.invoiced == False:
                    vals = self._prepare_service_invoice_line_purchase(cr, uid, group, picking_id, po_line,
                                invoice_id, context=context)
                    if vals:
                        invoice_line_id = invoice_line_obj.create(cr, uid, vals, context=context)
                        invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)
                        invoice_obj.button_compute(cr, uid, [invoice_id], context=context,
                                    set_total=(invoice.type in ('in_invoice', 'in_refund')))
                         
                        purchase_line_obj.write(cr, uid, po_line.id,
                            {"invoiced": True}, context = context)
        
        #same logic for sales
        #exclude service lines if refund as normally freight is not credited
        
        if inv_type == 'out_invoice':
            sale_line_obj=self.pool.get('sale.order.line')
            invoice_line_obj=self.pool.get('account.invoice.line')
            invoice_obj = self.pool.get('account.invoice')
            picking_obj=self.pool.get('stock.picking')
            
            pick_ids = picking_obj.browse(cr, uid, picking_id, context = context)
            sale_ids = pick_ids.sale_id.id
            so_lines = sale_line_obj.search(cr, uid, [('order_id', 'in', [sale_ids])], context=context)  
            for so_line in so_lines:
                so_line=sale_line_obj.browse(cr, uid, so_line, context=context)
                if (not so_line.product_id and so_line.invoiced == False) or (so_line.product_id and (so_line.product_id.product_tmpl_id.type == 'service' and so_line.invoiced == False)):
                    vals = self._prepare_service_invoice_line_sale(cr, uid, group, picking_id, so_line,
                                invoice_id, context=context)
                    ctx = context
                    ctx['do_check_price_processing'] = False
                    if vals:
                        invoice_line_id = invoice_line_obj.create(cr, uid, vals, context=context)
                        invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)
                        invoice_obj.button_compute(cr, uid, [invoice_id], context=context,
                                        set_total=(invoice.type in ('out_invoice', 'out_refund')))
                             
                        sale_line_obj.write(cr, uid, [so_line.id],
                                {"invoice_lines": [(4,invoice_line_id)]}, context = ctx)

        return res
    
    def _alt_get_invoice_type(self, pick):
        if pick.type == 'out' and pick.purchase_id:
                inv_type = 'in_refund'
        elif pick.type == 'out' and pick.sale_id:
                inv_type = 'out_invoice'
        elif pick.type == 'in' and pick.purchase_id:
                inv_type = 'in_invoice'
        elif pick.type == 'in' and pick.sale_id:
                inv_type = 'out_refund'
        else:
                inv_type = 'out_invoice'
        
        return inv_type
    
    def _prepare_service_invoice_line_purchase(self, cr, uid, group, picking, po_line, invoice_id, context=None):
        if group:
            name = (picking.name or '')
        else:
            name = po_line.order_id.name
        origin = ''

        account_id = po_line.product_id.property_account_expense.id
        if not account_id:
            account_id = po_line.product_id.categ_id.\
                    property_account_expense_categ.id
        invoice_obj=self.pool.get('account.invoice')
        invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)
        
        if invoice.fiscal_position:
            fp_obj = self.pool.get('account.fiscal.position')
            fiscal_position = fp_obj.browse(cr, uid, invoice.fiscal_position.id, context=context)
            account_id = fp_obj.map_account(cr, uid, fiscal_position, account_id)
        uos_id = po_line.product_uom.id
        
        return {
            'name': name,
            'origin': origin,
            'invoice_id': invoice_id,
            'uos_id': uos_id,
            'product_id': po_line.product_id.id,
            'account_id': account_id,
            'price_unit': po_line.price_unit,
            'discount': 0.0,
            'quantity': po_line.product_qty,
            'invoice_line_tax_id': [(6, 0, self._get_taxes_service_line_purchase(cr, uid, po_line, invoice.type))],
            'account_analytic_id': self._get_account_analytic_invoice_service_line_purchase(cr, uid,  po_line),
        }             

    def _get_taxes_service_line_purchase(self, cursor, user, po_line, type):
            return [x.id for x in po_line.taxes_id]
    
    def _get_account_analytic_invoice_service_line_purchase(self, cursor, user,  po_line):
            return po_line.account_analytic_id.id
    
    def _prepare_service_invoice_line_sale(self, cr, uid, group, picking, so_line, invoice_id, context=None):
        if group:
            name = (picking.name or '')
        else:
            name = so_line.order_id.name
        origin = ''
        uos_id = False
        account_id=False
        if so_line.product_id:
            uos_id = so_line.product_uom.id
            account_id = so_line.product_id.property_account_expense.id
            if not account_id:
                account_id = so_line.product_id.categ_id.\
                    property_account_expense_categ.id
        else:
            #find the first sales journal and use the default credit account or throw an error
            account_journal_obj = self.pool.get('account.journal')
            journal_ids = account_journal_obj.search(cr, uid, [('type','=','sale')], context=context)
            journal_id = account_journal_obj.browse(cr, uid, journal_ids[0], context=context)
            account_id = journal_id.default_credit_account_id.id
            if not account_id:
                raise osv.except_osv(('Error!'),('There is no default credit account for a sale journal'))
            name = so_line.name
                
        invoice_obj=self.pool.get('account.invoice')
        invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)
        
        if invoice.fiscal_position:
            fp_obj = self.pool.get('account.fiscal.position')
            fiscal_position = fp_obj.browse(cr, uid, invoice.fiscal_position.id, context=context)
            account_id = fp_obj.map_account(cr, uid, fiscal_position, account_id)
        

        return {
            'name': name,
            'origin': origin,
            'invoice_id': invoice_id,
            'uos_id': uos_id or False,
            'product_id': so_line.product_id.id or False,
            'account_id': account_id or False,
            'price_unit': so_line.price_unit,
            'discount': so_line.discount,
            'quantity': so_line.product_uom_qty or False,
            'invoice_line_tax_id': [(6, 0, self._get_taxes_service_line_sales(cr, uid, so_line, invoice.type))],
            'account_analytic_id': self._get_account_analytic_invoice_service_line_sales(cr, uid,  so_line),
        }             

    def _get_taxes_service_line_sales(self, cursor, user, so_line, type):
            return [x.id for x in so_line.tax_id]
    
    def _get_account_analytic_invoice_service_line_sales(self, cursor, user,  so_line):
            try:
                analytic_account= so_line.account_analytic_id.id
                return so_line.account_analytic_id.id
            except:
                return ''
   
    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        default = default.copy()
        default.update({'invoice_ids': [],})
        return super(stock_picking, self).copy(cr, uid, id, default, context)
    
    def do_partial(self, cr, uid, ids, partial_datas, context=None):
        """ This is a straight copy & paste from core
            as the changes are required in the middle of the code
            to handle purchase returns properly"""
            
        """ Makes partial pickings and moves done.
        @param partial_datas: Dictionary containing details of partial picking
                          like partner_id, address_id, delivery_date, delivery
                          moves with product_id, product_qty, uom
        """
        if context is None:
            context = {}
        else:
            context = dict(context)
        res = {}
        move_obj = self.pool.get('stock.move')
        product_obj = self.pool.get('product.product')
        currency_obj = self.pool.get('res.currency')
        uom_obj = self.pool.get('product.uom')
        sequence_obj = self.pool.get('ir.sequence')
        wf_service = netsvc.LocalService("workflow")
        for pick in self.browse(cr, uid, ids, context=context):
            new_picking = None
            complete, too_many, too_few = [], [], []
            move_product_qty, prodlot_ids, product_avail, partial_qty, product_uoms = {}, {}, {}, {}, {}
            for move in pick.move_lines:
                if move.state in ('done', 'cancel'):
                    continue
                partial_data = partial_datas.get('move%s'%(move.id), {})
                product_qty = partial_data.get('product_qty',0.0)
                move_product_qty[move.id] = product_qty
                product_uom = partial_data.get('product_uom',False)
                product_price = partial_data.get('product_price',0.0)
                product_currency = partial_data.get('product_currency',False)
                prodlot_id = partial_data.get('prodlot_id')
                prodlot_ids[move.id] = prodlot_id
                product_uoms[move.id] = product_uom
                partial_qty[move.id] = uom_obj._compute_qty(cr, uid, product_uoms[move.id], product_qty, move.product_uom.id)
                if move.product_qty == partial_qty[move.id]:
                    complete.append(move)
                elif move.product_qty > partial_qty[move.id]:
                    too_few.append(move)
                else:
                    too_many.append(move)


            # Average price computation
                #2/4/2013 - have raised bug report 1163060 (see also 610738) to get the change made below
                #included in the core product. The problem is that purchase returns were
                #not being catered for - code below does.
                #the bug exists in V7 so can be fixed there.
                 
                if pick.purchase_id and move.product_id.cost_method == 'average':
                    product = product_obj.browse(cr, uid, move.product_id.id)
                    move_currency_id = move.company_id.currency_id.id
                    context['currency_id'] = move_currency_id
                    qty = uom_obj._compute_qty(cr, uid, product_uom, product_qty, product.uom_id.id)
                    
                    #for a return, get the price from the move. if none, use average cost
                    if pick.type == 'out':
                        if move.price_unit:
                            product_price = move.price_unit
                        else:
                            product_price = product.price_get('standard_price', context)[product.id]
                    
                    new_price = currency_obj.compute(cr, uid, product_currency,
                                move_currency_id, product_price)
                    new_price = uom_obj._compute_price(cr, uid, product_uom, new_price,
                                product.uom_id.id)
    
    #                    if qty <= 0:
                    if pick.type == 'in':
                        if product.qty_available <= 0:
                            new_std_price = new_price
                        else:
                            # Get the standard price
                            amount_unit = product.price_get('standard_price', context)[product.id]
                            new_std_price = ((amount_unit * product.qty_available)\
                                + (new_price * qty))/(product.qty_available + qty)
                                
                    else:
                        amount_unit = product.price_get('standard_price', context)[product.id]
                        if product.qty_available - qty <= 0:
                            #will not matter as the next purchase will set the new average cost as per above
                            new_std_price = amount_unit
                        else:
                            # Get the standard price
                            new_std_price = ((amount_unit * product.qty_available)\
                                + (new_price * (0-qty)))/(product.qty_available -qty)
                        
                        # Write the field according to price type field
                    product_obj.write(cr, uid, [product.id], {'standard_price': new_std_price})
    
                        # Record the values that were chosen in the wizard, so they can be
                        # used for inventory valuation if real-time valuation is enabled.
                    move_obj.write(cr, uid, [move.id],
                                {'price_unit': product_price,
                                 'price_currency_id': product_currency})
    
                #this section handles customer returns
                elif pick.sale_id and move.product_id.cost_method == 'average' and pick.type == 'in':
                    product = product_obj.browse(cr, uid, move.product_id.id)
                    move_currency_id = move.company_id.currency_id.id
                    context['currency_id'] = move_currency_id
                    qty = uom_obj._compute_qty(cr, uid, product_uom, product_qty, product.uom_id.id)    
                    
                    #for a return, get the price from the move. if none, use average cost
                    if move.price_unit:
                        product_price = move.price_unit
                    else:
                        product_price = product.price_get('standard_price', context)[product.id]
                    
                    new_price = currency_obj.compute(cr, uid, product_currency,
                                move_currency_id, product_price)
                    new_price = uom_obj._compute_price(cr, uid, product_uom, new_price,
                                product.uom_id.id)
                
                    if product.qty_available <= 0:
                            new_std_price = new_price
                    else:
                        # Get the standard price
                        amount_unit = product.price_get('standard_price', context)[product.id]
                        new_std_price = ((amount_unit * product.qty_available)\
                            + (new_price * qty))/(product.qty_available + qty)
                    
                        # Write the field according to price type field
                    product_obj.write(cr, uid, [product.id], {'standard_price': new_std_price})
    
                        # Record the values that were chosen in the wizard, so they can be
                        # used for inventory valuation if real-time valuation is enabled.
                    move_obj.write(cr, uid, [move.id],
                                {'price_unit': product_price,
                                 'price_currency_id': product_currency})
                
                #writing the average cost to the move record
                #so that it can be used for a sale return
                #09/01/2014 KM - for a SO line that is related to a PO linewe have already written the PO
                #cost to the move, so do not want to update 
                
                elif pick.sale_id and move.product_id.cost_method == 'average' and pick.type == 'out' and move.price_unit ==0:
                    product = product_obj.browse(cr, uid, move.product_id.id)
                    move_currency_id = move.company_id.currency_id.id
                    context['currency_id'] = move_currency_id
                    qty = uom_obj._compute_qty(cr, uid, product_uom, product_qty, product.uom_id.id)    
                    product_price = product.price_get('standard_price', context)[product.id]
                    move_obj.write(cr, uid, [move.id],
                                {'price_unit': product_price,
                                 'price_currency_id': product_currency})
            
        
        
        
            for move in too_few:
                product_qty = move_product_qty[move.id]
                if not new_picking:
                    new_picking_name = pick.name
                    self.write(cr, uid, [pick.id], 
                               {'name': sequence_obj.get(cr, uid,
                                            'stock.picking.%s'%(pick.type)),
                               })
                    new_picking = self.copy(cr, uid, pick.id,
                            {
                                'name': new_picking_name,
                                'move_lines' : [],
                                'state':'draft',
                            })
                if product_qty != 0:
                    defaults = {
                            'product_qty' : product_qty,
                            'product_uos_qty': product_qty, #TODO: put correct uos_qty
                            'picking_id' : new_picking,
                            'state': 'assigned',
                            'move_dest_id': False,
                            'price_unit': move.price_unit,
                            'product_uom': product_uoms[move.id]
                    }
                    prodlot_id = prodlot_ids[move.id]
                    if prodlot_id:
                        defaults.update(prodlot_id=prodlot_id)
                    move_obj.copy(cr, uid, move.id, defaults)
                move_obj.write(cr, uid, [move.id],
                        {
                            'product_qty': move.product_qty - partial_qty[move.id],
                            'product_uos_qty': move.product_qty - partial_qty[move.id], #TODO: put correct uos_qty
                            'prodlot_id': False,
                            'tracking_id': False,
                        })

            if new_picking:
                move_obj.write(cr, uid, [c.id for c in complete], {'picking_id': new_picking})
            for move in complete:
                defaults = {'product_uom': product_uoms[move.id], 'product_qty': move_product_qty[move.id]}
                if prodlot_ids.get(move.id):
                    defaults.update({'prodlot_id': prodlot_ids[move.id]})
                move_obj.write(cr, uid, [move.id], defaults)
            for move in too_many:
                product_qty = move_product_qty[move.id]
                defaults = {
                    'product_qty' : product_qty,
                    'product_uos_qty': product_qty, #TODO: put correct uos_qty
                    'product_uom': product_uoms[move.id]
                }
                prodlot_id = prodlot_ids.get(move.id)
                if prodlot_ids.get(move.id):
                    defaults.update(prodlot_id=prodlot_id)
                if new_picking:
                    defaults.update(picking_id=new_picking)
                move_obj.write(cr, uid, [move.id], defaults)

            # At first we confirm the new picking (if necessary)
            if new_picking:
                wf_service.trg_validate(uid, 'stock.picking', new_picking, 'button_confirm', cr)
                # Then we finish the good picking
                self.write(cr, uid, [pick.id], {'backorder_id': new_picking})
                self.action_move(cr, uid, [new_picking], context=context)
                wf_service.trg_validate(uid, 'stock.picking', new_picking, 'button_done', cr)
                wf_service.trg_write(uid, 'stock.picking', pick.id, cr)
                delivered_pack_id = new_picking
                back_order_name = self.browse(cr, uid, delivered_pack_id, context=context).name
                self.message_post(cr, uid, ids, body = "Back order <em>%s</em> has been <b>created</b>." % (back_order_name), context=context)
            else:
                self.action_move(cr, uid, [pick.id], context=context)
                wf_service.trg_validate(uid, 'stock.picking', pick.id, 'button_done', cr)
                delivered_pack_id = pick.id

            delivered_pack = self.browse(cr, uid, delivered_pack_id, context=context)
            res[pick.id] = {'delivered_picking': delivered_pack.id or False}

    

stock_picking()

class product_product(osv.osv):
    _inherit = "product.product"

    def do_change_standard_price(self, cr, uid, ids, datas, context=None):
        """ this is a copy and paste from stock/product
            the non-inventory leg of the journal should go to price variance account
            bug logged 1174045 - once fixed should be able to go back to core 

        """
        location_obj = self.pool.get('stock.location')
        move_obj = self.pool.get('account.move')
        move_line_obj = self.pool.get('account.move.line')
        product_obj = self.pool.get('product.product')
        if context is None:
            context = {}
        
        product_ids = product_obj.browse(cr, uid, ids, context = context)
        for product_id in product_ids:
            price_difference_account = product_id.property_account_creditor_price_difference.id
            if not price_difference_account:
                price_difference_account = product_id.product_tmpl_id.categ_id.property_account_creditor_price_difference_categ.id
            if not price_difference_account:
                raise osv.except_osv(('Error!'),('There is no price difference account defined ' \
                            'for this product: "%s" (id: %d)') % (product_obj.name, product_obj.id,))
        new_price = datas.get('new_price', 0.0)
        journal_id = datas.get('stock_journal', False)
        product_obj=self.browse(cr, uid, ids, context=context)[0]
        account_valuation = product_obj.categ_id.property_stock_valuation_account_id
        account_valuation_id = account_valuation and account_valuation.id or False
        if not account_valuation_id: raise osv.except_osv(('Error!'), ('Specify valuation Account for Product Category: %s.') % (product_obj.categ_id.name))
        move_ids = []
        loc_ids = location_obj.search(cr, uid,[('usage','=','internal')])
        for rec_id in ids:
            for location in location_obj.browse(cr, uid, loc_ids, context=context):
                c = context.copy()
                c.update({
                    'location': location.id,
                    'compute_child': False
                })

                product = self.browse(cr, uid, rec_id, context=c)
                qty = product.qty_available
                diff = product.standard_price - new_price
                if not diff: raise osv.except_osv(('Error!'), ("No difference between standard price and new price!"))
                if qty and qty > 0:
                    company_id = location.company_id and location.company_id.id or False
                    if not company_id: raise osv.except_osv(('Error!'), ('Please specify company in Location.'))
                    #
                    # Accounting Entries
                    #
                    if not journal_id:
                        journal_id = product.categ_id.property_stock_journal and product.categ_id.property_stock_journal.id or False
                    if not journal_id:
                        raise osv.except_osv(('Error!'),
                            ('Please define journal '\
                              'on the product category: "%s" (id: %d).') % \
                                (product.categ_id.name,
                                    product.categ_id.id,))
                    move_id = move_obj.create(cr, uid, {
                                'journal_id': journal_id,
                                'company_id': company_id
                                })

                    move_ids.append(move_id)


                    if diff > 0:
                        amount_diff = qty * diff
                        move_line_obj.create(cr, uid, {
                                    'name': product.name,
                                    'account_id': price_difference_account,
                                    'debit': amount_diff,
                                    'move_id': move_id,
                                    })
                        move_line_obj.create(cr, uid, {
                                    'name': product.categ_id.name,
                                    'account_id': account_valuation_id,
                                    'credit': amount_diff,
                                    'move_id': move_id
                                    })
                    elif diff < 0:
                        amount_diff = qty * -diff
                        move_line_obj.create(cr, uid, {
                                        'name': product.name,
                                        'account_id': price_difference_account,
                                        'credit': amount_diff,
                                        'move_id': move_id
                                    })
                        move_line_obj.create(cr, uid, {
                                        'name': product.categ_id.name,
                                        'account_id': account_valuation_id,
                                        'debit': amount_diff,
                                        'move_id': move_id
                                    })

            self.write(cr, uid, rec_id, {'standard_price': new_price})

        return move_ids
    
    
    def get_product_accounts(self, cr, uid, product_id, context=None):
        """ 
        Copy & paste from original as need to get the stock expense account as well for accounting entries
        
        To get the stock input account, stock output account, stock expense account and stock journal related to product.
        @param product_id: product id
        @return: dictionary which contains information regarding stock input account, stock output account, stock expense and stock journal
        """
        if context is None:
            context = {}
        product_obj = self.pool.get('product.product').browse(cr, uid, product_id, context=context)

        stock_input_acc = product_obj.property_stock_account_input and product_obj.property_stock_account_input.id or False
        if not stock_input_acc:
            stock_input_acc = product_obj.categ_id.property_stock_account_input_categ and product_obj.categ_id.property_stock_account_input_categ.id or False

        stock_output_acc = product_obj.property_stock_account_output and product_obj.property_stock_account_output.id or False
        if not stock_output_acc:
            stock_output_acc = product_obj.categ_id.property_stock_account_output_categ and product_obj.categ_id.property_stock_account_output_categ.id or False
        
        stock_expense_acc = product_obj.property_account_expense and product_obj.property_account_expense.id or False
        if not stock_expense_acc:
            stock_expense_acc = product_obj.categ_id.property_account_expense_categ and product_obj.categ_id.property_account_expense_categ.id or False
   
        journal_id = product_obj.categ_id.property_stock_journal and product_obj.categ_id.property_stock_journal.id or False
        account_valuation = product_obj.categ_id.property_stock_valuation_account_id and product_obj.categ_id.property_stock_valuation_account_id.id or False

        return {
            'stock_account_input': stock_input_acc,
            'stock_account_output': stock_output_acc,
            'stock_expense_account': stock_expense_acc,
            'stock_journal': journal_id,
            'property_stock_valuation': account_valuation
        }


product_product()

class stock_move(osv.osv):
    
    _inherit = "stock.move"
    
    
    def _create_product_valuation_moves(self, cr, uid, move, context=None):
        """
        Generate the appropriate accounting moves if the product being moves is subject
        to real_time valuation tracking, and the source or destination location is
        a transit location or is outside of the company.
        
        The code from our version from v6 as standard openerp does not cater correctly for
        possible move situations and correct accounting treatment
        """
        
        
        if move.product_id.valuation == 'real_time': # FIXME: product valuation should perhaps be a property?
            if context is None:
                context = {}
            src_company_ctx = dict(context,force_company=move.location_id.company_id.id)
            dest_company_ctx = dict(context,force_company=move.location_dest_id.company_id.id)
            account_moves = []
        
        # Outgoing moves for a customer
            if move.location_id.usage == 'internal' and move.location_dest_id.usage == 'customer':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_dest, reference_amount, reference_currency_id, context))]
                
            # Incoming moves for a customer where an invoice is being generated
            elif move.location_id.usage == 'customer' and move.location_dest_id.usage == 'internal' \
                and move.picking_id.invoice_state == '2binvoiced':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_dest, acc_valuation, reference_amount, reference_currency_id, context))]
            
            # Incoming moves for a customer where an invoice is not being generated
            elif move.location_id.usage == 'customer' and move.location_dest_id.usage == 'internal' \
                and move.picking_id.invoice_state != '2binvoiced':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_exp, acc_valuation, reference_amount, reference_currency_id, context))]
            
            # Incoming moves for a supplier
            elif move.location_id.usage == 'supplier' and move.location_dest_id.usage == 'internal':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_src, acc_valuation, reference_amount, reference_currency_id, context))]
                   
            # Outgoing moves for a supplier where a credit invoice is being generated
            elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'supplier'\
                and move.picking_id.invoice_state == '2binvoiced':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_src, reference_amount, reference_currency_id, context))]
             
            # Outgoing moves for a supplier where an invoice is not being generated
            elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'supplier'\
                and move.picking_id.invoice_state != '2binvoiced':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_exp, reference_amount, reference_currency_id, context))]
             
            # Ingoing moves for a production order
            #this code works correctly if the GL account for the COS to be posted to is specified in the production location setup
            elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'production':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_dest, reference_amount, reference_currency_id, context))]
                
            # Outgoing moves for a production order
            elif move.location_id.usage == 'production' and move.location_dest_id.usage == 'internal':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_src,acc_valuation, reference_amount, reference_currency_id, context))]
                   
            # Stock-take accounting for count > soh
            #KM 3/3/14 changed so uses expense account as more accurate
            elif move.location_id.usage == 'inventory' and move.location_dest_id.usage == 'internal':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
#                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_src,acc_valuation, reference_amount, reference_currency_id, context))]
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_exp,acc_valuation, reference_amount, reference_currency_id, context))]     

            # Stock-take accounting for count < soh
            #KM 3/3/14 changed so uses expense account as more accurate
            elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'inventory':
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
#                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation ,acc_dest, reference_amount, reference_currency_id, context))]    
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation ,acc_exp, reference_amount, reference_currency_id, context))]
                
            # cross-company output part
            elif move.location_id.company_id \
                and move.location_id.company_id != move.location_dest_id.company_id:
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_dest, reference_amount, reference_currency_id, context))]
                
            # cross-company input part
            elif move.location_id.company_id \
                and move.location_id.company_id != move.location_dest_id.company_id:
                journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
                reference_amount, reference_currency_id = self._get_reference_accounting_values_for_valuation(cr, uid, move, src_company_ctx)
                account_moves += [(journal_id, self._create_account_move_line(cr, uid, move, acc_valuation, acc_src, reference_amount, reference_currency_id, context))]    
             
            

            move_obj = self.pool.get('account.move')
            for j_id, move_lines in account_moves:
                move_obj.create(cr, uid,
                        {
                         'journal_id': j_id,
                         'line_id': move_lines,
                         'ref': move.picking_id and move.picking_id.name})


    def _get_accounting_data_for_valuation(self, cr, uid, move, context=None):
        """
        This is a copy & paste of original code to add stock_expense_account which is missing
        from standard openerp.
        
        Return the accounts and journal to use to post Journal Entries for the real-time
        valuation of the move.

        :param context: context dictionary that can explicitly mention the company to consider via the 'force_company' key
        :raise: osv.except_osv() is any mandatory account or journal is not defined.
        """
        product_obj=self.pool.get('product.product')
        accounts = product_obj.get_product_accounts(cr, uid, move.product_id.id, context)
        if move.location_id.valuation_out_account_id:
            acc_src = move.location_id.valuation_out_account_id.id
        else:
            acc_src = accounts['stock_account_input']

        if move.location_dest_id.valuation_in_account_id:
            acc_dest = move.location_dest_id.valuation_in_account_id.id
        else:
            acc_dest = accounts['stock_account_output']

        acc_exp = accounts.get('stock_expense_account')  
        acc_valuation = accounts.get('property_stock_valuation', False)
        journal_id = accounts['stock_journal']

        if acc_dest == acc_valuation:
            raise osv.except_osv(('Error!'),  ('Can not create Journal Entry, Output Account defined on this product and Variant account on category of this product are same.'))

        if acc_src == acc_valuation:
            raise osv.except_osv(('Error!'),  ('Can not create Journal Entry, Input Account defined on this product and Variant account on category of this product are same.'))

        if not acc_src:
            raise osv.except_osv(('Error!'),  ('There is no stock input account defined for this product or its category: "%s" (id: %d)') % \
                                    (move.product_id.name, move.product_id.id,))
        if not acc_dest:
            raise osv.except_osv(('Error!'),  ('There is no stock output account defined for this product or its category: "%s" (id: %d)') % \
                                    (move.product_id.name, move.product_id.id,))
        if not journal_id:
            raise osv.except_osv(('Error!'), ('There is no journal defined on the product category: "%s" (id: %d)') % \
                                    (move.product_id.categ_id.name, move.product_id.categ_id.id,))
        if not acc_valuation:
            raise osv.except_osv(('Error!'), ('There is no inventory valuation account defined on the product category: "%s" (id: %d)') % \
                                    (move.product_id.categ_id.name, move.product_id.categ_id.id,))
        return journal_id, acc_src, acc_dest, acc_exp, acc_valuation

stock_move()



# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
