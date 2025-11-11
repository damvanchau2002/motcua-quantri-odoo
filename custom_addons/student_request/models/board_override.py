from odoo import models, api


class BoardOverride(models.AbstractModel):
    _inherit = 'board.board'

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        """Ensure a per-user custom view exists so dashboard edits work.

        The stock board implementation only returns a custom_view_id if an
        existing ir.ui.view.custom is found. When users first open the board,
        there is no custom record and saving layout triggers a server error
        because /web/view/edit_custom requires a custom_id.

        We create a custom view for the current user the first time they open
        the dashboard, using the resolved arch produced by the base method.
        """
        res = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_id and not res.get('custom_view_id'):
            custom_view = self.env['ir.ui.view.custom'].sudo().create({
                'user_id': self.env.uid,
                'ref_id': view_id,
                'arch': res.get('arch'),
            })
            res['custom_view_id'] = custom_view.id
        # Sanitize arch to avoid null contexts breaking board actions
        res['arch'] = self._sanitize_board_arch(res['arch'])
        return res

    def _sanitize_board_arch(self, arch):
        """Remove invalid context attributes like context="null" from action nodes."""
        from lxml import etree
        try:
            root = etree.fromstring(arch)
        except Exception:
            return arch
        # ensure js_class is set as in base implementation
        root.set('js_class', 'board')

        def clean(node):
            for child in list(node):
                if child.tag == 'action':
                    ctx = child.get('context')
                    if ctx is not None:
                        val = ctx.strip().lower()
                        if val in ('null', 'none', ''):
                            # drop invalid context attribute
                            if 'context' in child.attrib:
                                del child.attrib['context']
                clean(child)
            return node

        cleaned = clean(root)
        return etree.tostring(cleaned, pretty_print=True, encoding='unicode')