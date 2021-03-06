from dimagi.ext.jsonobject import (
    BooleanProperty,
    JsonObject,
    ListProperty,
    StringProperty,
    DictProperty,
)
from jsonobject.base import DefaultProperty
from corehq.apps.userreports.indicators.specs import DataTypeProperty
from corehq.apps.userreports.reports.filters.choice_providers import DATA_SOURCE_COLUMN
from corehq.apps.userreports.reports.filters.values import (
    PreFilterValue,
    ChoiceListFilterValue,
    DateFilterValue,
    NumericFilterValue,
    QuarterFilterValue)
from corehq.apps.userreports.specs import TypeProperty


class ReportFilter(JsonObject):
    """
    This is a spec class that is just used for validation on a ReportConfiguration object.

    These get converted to FilterSpecs (below) by the FilterFactory.
    """
    # todo: this class is silly and can likely be removed.
    type = StringProperty(required=True)
    slug = StringProperty(required=True)
    field = StringProperty(required=True)
    display = DefaultProperty()
    compare_as_string = BooleanProperty(default=False)

    def create_filter_value(self, value):
        return {
            'quarter': QuarterFilterValue,
            'date': DateFilterValue,
            'numeric': NumericFilterValue,
            'pre': PreFilterValue,
            'choice_list': ChoiceListFilterValue,
            'dynamic_choice_list': ChoiceListFilterValue,
        }[self.type](self, value)


class FilterChoice(JsonObject):
    value = DefaultProperty()
    display = StringProperty()

    def get_display(self):
        return self.display or self.value


class FilterSpec(JsonObject):
    """
    This is the spec for a report filter - a thing that should show up as a UI filter element
    in a report (like a date picker or a select list).
    """
    type = StringProperty(
        required=True,
        choices=['date', 'quarter', 'numeric', 'pre', 'choice_list', 'dynamic_choice_list']
    )
    # this shows up as the ID in the filter HTML.
    slug = StringProperty(required=True)
    field = StringProperty(required=True)  # this is the actual column that is queried
    display = DefaultProperty()
    datatype = DataTypeProperty(default='string')

    def get_display(self):
        return self.display or self.slug


class DateFilterSpec(FilterSpec):
    compare_as_string = BooleanProperty(default=False)


class QuarterFilterSpec(FilterSpec):
    type = TypeProperty('quarter')


class ChoiceListFilterSpec(FilterSpec):
    type = TypeProperty('choice_list')
    show_all = BooleanProperty(default=True)
    datatype = DataTypeProperty(default='string')
    choices = ListProperty(FilterChoice)


class DynamicChoiceListFilterSpec(FilterSpec):
    type = TypeProperty('dynamic_choice_list')
    show_all = BooleanProperty(default=True)
    datatype = DataTypeProperty(default='string')
    choice_provider = DictProperty()

    def get_choice_provider_spec(self):
        return self.choice_provider or {'type': DATA_SOURCE_COLUMN}

    @property
    def choices(self):
        return []


class PreFilterSpec(FilterSpec):
    type = TypeProperty('pre')
    pre_value = DefaultProperty(required=True)
    pre_operator = StringProperty(default=None, required=False)


class NumericFilterSpec(FilterSpec):
    type = TypeProperty('numeric')
