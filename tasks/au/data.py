import os
import csv
import re
import glob

from luigi import Parameter, IntParameter, WrapperTask
from collections import OrderedDict

from lib.timespan import get_timespan
from tasks.util import shell
from tasks.base_tasks import ColumnsTask, RepoFileUnzipTask, TableTask, CSV2TempTableTask, MetaWrapper
from tasks.meta import current_session, OBSColumn, GEOM_REF
from tasks.au.geo import (SourceTags, LicenseTags, GEOGRAPHIES, GeographyColumns, Geography, GEO_MB, GEO_SA1)
from tasks.tags import SectionTags, SubsectionTags, UnitTags

from lib.logger import get_logger

LOGGER = get_logger(__name__)

PROFILES = {
    2011: 'BCP',
    2016: 'GCP',
}

STATES = ('NSW', 'Vic', 'Qld', 'SA', 'WA', 'Tas', 'NT', 'ACT', 'OT', )

TABLES = {
    2011: ['B01', 'B02', 'B03', 'B04A', 'B04B', 'B05', 'B06', 'B07', 'B08A', 'B08B', 'B09', 'B10A', 'B10B', 'B10C',
           'B11A', 'B11B', 'B12A', 'B12B', 'B13', 'B14', 'B15', 'B16A', 'B16B', 'B17A', 'B17B', 'B18', 'B19',
           'B20A', 'B20B', 'B21', 'B22A', 'B22B', 'B23A', 'B23B', 'B24', 'B25', 'B26', 'B27', 'B28', 'B29', 'B30',
           'B31', 'B32', 'B33', 'B34', 'B35', 'B36', 'B37', 'B38', 'B39', 'B40A', 'B40B', 'B41A', 'B41B', 'B41C',
           'B42A', 'B42B', 'B43A', 'B43B', 'B43C', 'B43D', 'B44A', 'B44B', 'B45A', 'B45B', 'B46', ],
    2016: ['G01', 'G02', 'G03', 'G04A', 'G04B', 'G05', 'G06', 'G07', 'G08',
           'G09A', 'G09B', 'G09C', 'G09D', 'G09E', 'G09F', 'G09G', 'G09H', 'G10A', 'G10B', 'G10C',
           'G11A', 'G11B', 'G11C', 'G12A', 'G12B', 'G13A', 'G13B', 'G13C', 'G14', 'G15', 'G16A', 'G16B',
           'G17A', 'G17B', 'G17C', 'G18', 'G19', 'G20A', 'G20B', 'G21', 'G22A', 'G22B', 'G23A', 'G23B', 'G24', 'G25',
           'G26', 'G27', 'G28', 'G29', 'G30', 'G31', 'G32', 'G33', 'G34', 'G35', 'G36', 'G37', 'G38', 'G39', 'G40',
           'G41', 'G42', 'G43A', 'G43B', 'G44A', 'G44B', 'G44C', 'G44D', 'G44E', 'G44F', 'G45A', 'G45B', 'G46A', 'G46B',
           'G47A', 'G47B', 'G47C', 'G48A', 'G48B', 'G48C', 'G49A', 'G49B', 'G49C', 'G50A', 'G50B', 'G50C',
           'G51A', 'G51B', 'G51C', 'G51D', 'G52A', 'G52B', 'G52C', 'G52D', 'G53A', 'G53B', 'G54A', 'G54B',
           'G55A', 'G55B', 'G56A', 'G56B', 'G57A', 'G57B', 'G58A', 'G58B', 'G59', ]
}

URL = 'http://www.censusdata.abs.gov.au/CensusOutput/copsubdatapacks.nsf/All%20docs%20by%20catNo/{year}_{profile}_{resolution}_for_{state}/$File/{year}_{profile}_{resolution}_for_{state}_{header}-header.zip'


class DownloadData(RepoFileUnzipTask):
    year = IntParameter()
    resolution = Parameter()
    profile = Parameter()
    state = Parameter()
    header = Parameter()

    def get_url(self):
        return URL.format(year=self.year,
                          profile=self.profile,
                          resolution=self.resolution,
                          state=self.state,
                          header=self.header)


class ImportData(CSV2TempTableTask):
    tablename = Parameter()
    year = IntParameter()
    resolution = Parameter()
    state = Parameter()
    profile = Parameter(default='BCP')
    header = Parameter(default='short')

    def requires(self):
        return DownloadData(resolution=self.resolution, profile=self.profile,
                            state=self.state, year=self.year, header=self.header)

    def input_csv(self):
        return glob.glob(os.path.join(self.input().path, '**',
                                      '{year}Census_{tablename}_{state}_{resolution}*.csv'.format(
                                        path=self.input().path,
                                        year=self.year,
                                        tablename=self.tablename,
                                        state=self.state.upper(),
                                        resolution=self.resolution,)), recursive=True)[0]

    def after_copy(self):
        session = current_session()
        query_columns = '''
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = '{schema}'
                        AND table_name   = lower('{table}');
                        '''.format(schema=self.output().schema,
                                   table=self.output().tablename)
        columns = session.execute(query_columns).fetchall()
        for column in columns:
            column_name = column[0]
            if column_name != column_name.strip():
                alter_column = '''
                               ALTER TABLE "{schema}".{table}
                               RENAME COLUMN "{old_column}" TO "{new_column}";
                               '''.format(schema=self.output().schema,
                                          table=self.output().tablename,
                                          old_column=column_name,
                                          new_column=column_name.strip())
                session.execute(alter_column)
                session.commit()


class ImportAllTables(WrapperTask):
    year = IntParameter()
    resolution = Parameter()
    state = Parameter()

    def requires(self):
        for table in TABLES:
            yield ImportData(resolution=self.resolution, state=self.state,
                             year=self.year, tablename=table)


class ImportAllStates(WrapperTask):
    year = IntParameter()
    resolution = Parameter()

    def requires(self):
        for state in STATES:
            yield ImportAllTables(resolution=self.resolution, state=state,
                                  year=self.year)


class ImportAllResolutions(WrapperTask):
    year = IntParameter()
    state = Parameter()

    def requires(self):
        for resolution in GEOGRAPHIES:
            yield ImportAllTables(resolution=resolution, state=self.state, year=self.year)


class ImportAll(WrapperTask):
    year = IntParameter()

    def requires(self):
        for resolution in GEOGRAPHIES:
            for state in STATES:
                yield ImportAllTables(resolution=resolution, state=state, year=self.year)


class Columns(ColumnsTask):
    year = IntParameter()
    profile = Parameter()
    tablename = Parameter()

    def requires(self):
        requirements = {
            'sections': SectionTags(),
            'subsections': SubsectionTags(),
            'units': UnitTags(),
            'source': SourceTags(),
            'license': LicenseTags()
        }
        # all tables except B01 require B01
        if self.tablename != 'B01':
            requirements['B01'] = Columns(tablename='B01', year=self.year, profile=self.profile)
        if self.tablename == 'B02':
            requirements['B01'] = Columns(tablename='B01', year=self.year, profile=self.profile)
            requirements['B17B'] = Columns(tablename='B17B', year=self.year, profile=self.profile)
        if self.tablename == 'B04A':
            requirements['B04B'] = Columns(tablename='B04B', year=self.year, profile=self.profile)
        if self.tablename == 'B08A':
            requirements['B08B'] = Columns(tablename='B08B', year=self.year, profile=self.profile)

        if self.tablename == 'B10A':
            requirements['B10B'] = Columns(tablename='B10B', year=self.year, profile=self.profile)
            requirements['B10C'] = Columns(tablename='B10C', year=self.year, profile=self.profile)
        if self.tablename == 'B10B':
            requirements['B10C'] = Columns(tablename='B10C', year=self.year, profile=self.profile)

        if self.tablename == 'B11A':
            requirements['B11B'] = Columns(tablename='B11B', year=self.year, profile=self.profile)

        if self.tablename == 'B12A':
            requirements['B12B'] = Columns(tablename='B12B', year=self.year, profile=self.profile)

        if self.tablename == 'B16A':
            requirements['B16B'] = Columns(tablename='B16B', year=self.year, profile=self.profile)

        if self.tablename == 'B17A':
            requirements['B17B'] = Columns(tablename='B17B', year=self.year, profile=self.profile)

        if self.tablename == 'B20A':
            requirements['B20B'] = Columns(tablename='B20B', year=self.year, profile=self.profile)

        if self.tablename == 'B22A':
            requirements['B22B'] = Columns(tablename='B22B', year=self.year, profile=self.profile)

        if self.tablename == 'B23A':
            requirements['B23B'] = Columns(tablename='B23B', year=self.year, profile=self.profile)

        pattern = re.compile('B2[6-8]')
        if pattern.match(self.tablename):
            requirements['B25'] = Columns(tablename='B25', year=self.year, profile=self.profile)

        pattern = re.compile('B3[1-6]')
        if pattern.match(self.tablename):
            requirements['B29'] = Columns(tablename='B29', year=self.year, profile=self.profile)

        if self.tablename == 'B40A':
            requirements['B40B'] = Columns(tablename='B40B', year=self.year, profile=self.profile)

        if self.tablename == 'B42A':
            requirements['B42B'] = Columns(tablename='B42B', year=self.year, profile=self.profile)

        if self.tablename == 'B44A':
            requirements['B44B'] = Columns(tablename='B44B', year=self.year, profile=self.profile)

        if self.tablename == 'B45A':
            requirements['B45B'] = Columns(tablename='B45B', year=self.year, profile=self.profile)

        if self.tablename == 'B41A':
            requirements['B41B'] = Columns(tablename='B41B', year=self.year, profile=self.profile)
            requirements['B41C'] = Columns(tablename='B41C', year=self.year, profile=self.profile)
        if self.tablename == 'B41B':
            requirements['B41C'] = Columns(tablename='B41C', year=self.year, profile=self.profile)

        if self.tablename == 'B43A':
            requirements['B43B'] = Columns(tablename='B43B', year=self.year, profile=self.profile)
            requirements['B43C'] = Columns(tablename='B43C', year=self.year, profile=self.profile)
            requirements['B43D'] = Columns(tablename='B43D', year=self.year, profile=self.profile)
        if self.tablename == 'B43B':
            requirements['B43C'] = Columns(tablename='B43C', year=self.year, profile=self.profile)
            requirements['B43D'] = Columns(tablename='B43D', year=self.year, profile=self.profile)
        if self.tablename == 'B43C':
            requirements['B43D'] = Columns(tablename='B43D', year=self.year, profile=self.profile)

        return requirements

    def version(self):
        return 7

    def columns(self):
        cols = OrderedDict()
        input_ = self.input()

        subsectiontags = input_['subsections']
        unittags = input_['units']
        country = input_['sections']['au']
        source = input_['source']['au-census']
        license = input_['license']['au-datapacks-license']

        # column req's from other tables
        column_reqs = {}
        for key, value in input_.items():
            if key.startswith(self.profile[0]):
                column_reqs.update(value)

        filepath = "meta/Metadata_{year}_{profile}_DataPack.csv".format(year=self.year, profile=self.profile)

        session = current_session()
        with open(os.path.join(os.path.dirname(__file__), filepath)) as csv_meta_file:
            reader = csv.reader(csv_meta_file, delimiter=',', quotechar='"')

            for line in reader:
                if not line[0].startswith(self.profile[0]):
                    continue

                # ignore tables we don't care about right now
                if not line[4].startswith(self.tablename):
                    continue

                col_id = line[1]            # B: short
                col_name = line[2]          # C: name
                denominators = line[3]      # D: denominators
                tablename = line[4]         # H: Tablename
                col_unit = line[5]          # F: unit
                col_subsections = line[6]   # G: subsection
                if tablename == '{}02'.format(self.profile[0]):
                    col_agg = line[8]       # I: AGG (for B02 only)
                else:
                    col_agg = None
                tabledesc = line[10]        # K: Table description

                denominators = denominators.split('|')

                targets_dict = {}
                for denom_id in denominators:
                    denom_id = denom_id.strip()
                    if not denom_id:
                        continue

                    reltype = 'denominator'
                    if col_agg in ['median', 'average']:
                        reltype = 'universe'

                    if denom_id in column_reqs:
                        targets_dict[column_reqs[denom_id].get(session)] = reltype
                    else:
                        targets_dict[cols[denom_id]] = reltype
                targets_dict.pop(None, None)

                cols[col_id] = OBSColumn(
                    id=col_id,
                    type='Numeric',
                    name=col_name,
                    description=tabledesc,
                    # Ranking of importance, sometimes used to favor certain measures in auto-selection
                    # Weight of 0 will hide this column from the user.  We generally use between 0 and 10
                    weight=5,
                    aggregate=col_agg or 'sum',
                    # Tags are our way of noting aspects of this measure like its unit, the country
                    # it's relevant to, and which section(s) of the catalog it should appear in
                    tags=[source, license, country, unittags[col_unit]],
                    targets=targets_dict
                )

                # append the rest of the subsection tags
                col_subsections = col_subsections.split('|')
                for subsection in col_subsections:
                    subsection = subsection.strip()
                    subsection_tag = subsectiontags[subsection]
                    cols[col_id].tags.append(subsection_tag)

        return cols


#####################################
# COPY TO OBSERVATORY
#####################################
class XCP(TableTask):
    tablename = Parameter()
    year = IntParameter()
    resolution = Parameter()

    def version(self):
        return 4

    def targets(self):
        return {
            self.input()['geo'].obs_table: GEOM_REF,
        }

    def requires(self):
        requirements = {
            'geo': Geography(resolution=self.resolution, year=self.year),
            'geometa': GeographyColumns(resolution=self.resolution, year=self.year),
            'meta': Columns(year=self.year, profile=PROFILES[self.year], tablename=self.tablename),
        }
        import_data = {}
        if self.resolution == GEO_MB:
            # We need to have the data from the parent geometries
            # in order to interpolate
            requirements['geo_sa1'] = Geography(resolution=GEO_SA1, year=self.year)
            requirements['data'] = XCP(tablename=self.tablename, year=self.year, resolution=GEO_SA1)
        else:
            for state in STATES:
                import_data[state] = ImportData(resolution=self.resolution,
                                                state=state, profile=PROFILES[self.year],
                                                tablename=self.tablename,
                                                year=self.year)
            requirements['data'] = import_data
        return requirements

    def table_timespan(self):
        return get_timespan(str(self.year))

    def columns(self):
        cols = OrderedDict()
        input_ = self.input()
        cols['region_id'] = input_['geometa']['geom_id']
        for colname, coltarget in input_['meta'].items():
            cols[colname] = coltarget
        return cols

    def _get_geoid(self):
        return 'region_id' if self.year == 2011 \
               else '{}_CODE_{}'.format(self.resolution, self.year)

    def populate(self):
        if self.resolution == GEO_MB:
            self.populate_mb()
        else:
            self.populate_general()

    def populate_mb(self):
        session = current_session()
        column_targets = self.columns()
        out_colnames = [oc.lower() for oc in list(column_targets.keys())]
        in_colnames = ['mb.geom_id as region_id']
        for ic in list(column_targets.keys()):
            if ic != 'region_id':
                in_colnames.append('round(cast(float8 ({ic} * (ST_Area(mb.the_geom)/ST_Area(sa1geo.the_geom))) as numeric), 2) as {ic}'.format(ic=ic.lower()))
        insert_query = '''
              INSERT INTO {output} ("{out_colnames}")
              SELECT {in_colnames}
              FROM {input_geo_mb} mb
              INNER JOIN {input_geo_sa1} sa1geo ON (mb.parent_id = sa1geo.geom_id)
              INNER JOIN {input_data} sa1data ON (mb.parent_id = sa1data.region_id)
              '''.format(output=self.output().table,
                         input_data=self.input()['data'].table,
                         input_geo_mb=self.input()['geo'].table,
                         input_geo_sa1=self.input()['geo_sa1'].table,
                         in_colnames=', '.join(in_colnames),
                         out_colnames='", "'.join(out_colnames))
        try:
            LOGGER.debug(insert_query)
            session.execute(insert_query)
        except Exception:
            session.rollback()

    def populate_general(self):
        session = current_session()
        column_targets = self.columns()
        out_colnames = [oc.lower() for oc in list(column_targets.keys())]

        failstates = []
        for state, input_ in self.input()['data'].items():
            intable = input_.table

            in_colnames = []
            for colname, target in column_targets.items():

                # weird trailing underscore for australia but no states
                if colname.endswith('Median_rent_weekly_') and \
                   ((self.resolution == 'RA' and state.lower() != 'aust') or
                    (self.resolution == 'SA4' and state.lower() in ('vic', 'wa', 'ot')) or
                    (self.resolution == 'SA3' and state.lower() in ('vic', 'wa')) or
                    (self.resolution == 'SA2' and state.lower() in ('vic', 'wa', 'nsw')) or
                    (self.resolution == 'SA1' and state.lower() in ('vic', 'wa', 'qld', 'nt', 'sa', 'nsw')) or
                    (self.resolution == 'GCCSA' and state.lower() in ('vic', 'wa', 'ot')) or
                    (self.resolution == 'LGA' and state.lower() in ('wa')) or
                    (self.resolution == 'SLA' and state.lower() in ('wa')) or
                    (self.resolution == 'SSC' and state.lower() in ('vic', 'wa', 'qld', 'nt', 'sa', 'nsw')) or
                    (self.resolution == 'POA' and state.lower() in ('wa', 'qld', 'nsw')) or
                    (self.resolution == 'CED' and state.lower() in ('vic', 'wa')) or
                    (self.resolution == 'SED' and state.lower() in ('wa', 'ot'))):
                        colname = colname.replace('Median_rent_weekly_', 'Median_rent_weekly')

                in_colnames.append('"{}"::{}'.format(
                    colname.replace(self.tablename + '_', ''),
                    target.get(session).type)
                )

            in_colnames[0] = '"{}"'.format(self._get_geoid())

            cmd = 'INSERT INTO {output} ("{out_colnames}") ' \
                  'SELECT {in_colnames} FROM {input} '.format(
                      output=self.output().table,
                      input=intable,
                      in_colnames=', '.join(in_colnames),
                      out_colnames='", "'.join(out_colnames))
            try:
                session.execute(cmd)
            except Exception as err:
                LOGGER.error(err)
                failstates.append(state)
                session.rollback()
        if failstates:
            raise Exception('Error with columns states: {}, resolution: {}, tablename: {}'.format(
                failstates, self.resolution, self.tablename))


class XCPAllTables(WrapperTask):
    year = IntParameter()
    resolution = Parameter()

    def requires(self):
        for table in TABLES:
            yield XCP(resolution=self.resolution, tablename=table, year=self.year)


class XCPAllGeographiesAllTables(WrapperTask):
    year = IntParameter()

    def requires(self):
        for resolution in GEOGRAPHIES:
            yield XCPAllTables(resolution=resolution, year=self.year)


class XCPMetaWrapper(MetaWrapper):
    resolution = Parameter()
    table = Parameter()
    year = IntParameter()

    params = {
        'resolution': GEOGRAPHIES,
        'table': TABLES,
        'year': [2011, 2016]
    }

    def tables(self):
        yield Geography(resolution=self.resolution, year=self.year)
        yield XCP(resolution=self.resolution, tablename=self.table, year=self.year)
