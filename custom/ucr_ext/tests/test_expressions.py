from datetime import date
from django.test import SimpleTestCase
from corehq.apps.userreports.specs import EvaluationContext



class RootPropertyNameExpressionTest(SimpleTestCase):
    def test_no_datatype(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_root_property_name",
            "property_name": "foo"
        })
        self.assertEqual(
            "foo_value",
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext({"foo": "foo_value"}, 0)
            )
        )
    
    def test_datatype(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_root_property_name",
            "property_name": "foo",
            "datatype": "integer",
        })
        self.assertEqual(
            5,
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext({"foo": "5"}, 0)
            )
        )


class IterateFromOpenedDateExpressionTest(SimpleTestCase):
    def test_not_closed(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_iterate_from_opened_date",
        })
        self.assertEqual(
            [0, 1, 2, 3, 4, 5, 6, 7, 8],
            self.expression(
                {
                    "opened_on": "2015-06-03T01:10:15.241903Z",
                    "modified_on": "2015-11-10T01:10:15.241903Z",
                    "closed": False
                }
            )
        )
    
    def test_closed(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_iterate_from_opened_date",
        })
        self.assertEqual(
            [0, 1, 2, 3, 4, 5],
            self.expression(
                {
                    "opened_on": "2015-06-03T01:10:15.241903Z",
                    "modified_on": "2015-11-10T01:10:15.241903Z",
                    "closed": True,
                    "closed_on": "2015-11-10T01:10:15.241903Z",
                }
            )
        )


class MonthExpressionsTest(SimpleTestCase):
    def test_month_start_date(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_month_start_date",
        })
        self.assertEqual(
            date(2015, 7, 1),
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext({"opened_on": "2015-06-03T01:10:15.241903Z",}, 1),
            )
        )

    def test_month_end_date(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_month_end_date",
        })
        self.assertEqual(
            date(2015, 7, 31),
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext({"opened_on": "2015-06-03T01:10:15.241903Z",}, 1),
            )
        )


class ParentIdExpressionTest(SimpleTestCase):
    def test_has_parent_id(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_parent_id",
        })
        self.assertEqual(
            "p_id",
            self.expression(
                {
                    "indices": [
                        {
                            "identifier": "mother",
                            "referenced_id": "m_id",
                        },
                        {
                            "identifier": "parent",
                            "referenced_id": "p_id",
                        }
                    ],
                }
            )
        )
    
    def test_no_parent_id(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_parent_id",
        })
        self.assertEqual(
            None,
            self.expression(
                {
                    "indices": [
                        {
                            "identifier": "mother",
                            "referenced_id": "m_id",
                        },
                    ],
                }
            )
        )


class OpenInMonthExpressionTest(SimpleTestCase):
    def test_not_closed(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_open_in_month",
        })
        self.assertEqual(
            "yes",
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext(
                    {
                        "opened_on": "2015-06-03T01:10:15.241903Z",
                        "closed": False,
                    }, 
                    3),
            )
        )

    def test_closed_open_in_month(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_open_in_month",
        })
        self.assertEqual(
            "yes",
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext(
                    {
                        "opened_on": "2015-06-03T01:10:15.241903Z",
                        "closed": True,
                        "closed_on": "2015-08-10T01:10:15.241903Z",
                    }, 
                    2),
            )
        )

    def test_closed_closed_in_month(self):
        expression=ExpressionFactory.from_spec({
            "type": "ext_open_in_month",
        })
        self.assertEqual(
            "no",
            self.expression(
                {"some_item": "item_value"},
                context=EvaluationContext(
                    {
                        "opened_on": "2015-06-03T01:10:15.241903Z",
                        "closed": True,
                        "closed_on": "2015-08-10T01:10:15.241903Z",
                    }, 
                    3),
            )
        )

        