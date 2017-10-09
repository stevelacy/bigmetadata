from collections import OrderedDict
import json
import os
import re

from tasks.meta import OBSColumn, DENOMINATOR, OBSTag
from tasks.util import ColumnsTask, TagsTask
from tasks.tags import UnitTags, SectionTags, SubsectionTags, LicenseTags


def load_definition():
    with open(os.path.join(os.path.dirname(__file__), 'columns.json')) as json_file:
        return json.load(json_file, object_pairs_hook=OrderedDict)


COLUMNS_DEFINITION = load_definition()


def parse_table(table_id):
    '''
    Returns a tuple like (KS, NI)
    '''
    return re.match('(\D+)\d+(\D+)', table_id).groups()


class SourceTags(TagsTask):
    def version(self):
        return 1

    def tags(self):
        return [OBSTag(id='ons',
                       name='Office for National Statistics (ONS)',
                       type='source',
                       description="The UK's largest independent producer of official statistics and the recognised national statistical institute of the UK (`ONS <https://www.ons.gov.uk/>`_)")]


class CensusColumns(ColumnsTask):
    def requires(self):
        return {
            'units': UnitTags(),
            'sections': SectionTags(),
            'subsections': SubsectionTags(),
            'source': SourceTags(),
            'license': LicenseTags(),
        }

    def version(self):
        return 4

    def columns(self):
        input_ = self.input()
        source = input_['source']['ons']
        license = input_['license']['uk_ogl']
        uk = input_['sections']['uk']
        subsections = input_['subsections']
        units = input_['units']

        columns = OrderedDict()
        for key, column in COLUMNS_DEFINITION.items():
            columns[key] = OBSColumn(
                id=column['id'],
                name=column['name'],
                description='',
                type='Numeric',
                weight=column['weight'],
                aggregate='sum',
                targets={columns[denom]: DENOMINATOR for denom in column['denominators']},
                tags=[uk, source, license, units[column['units']], subsections[column['subsection']]]
            )

        return columns
