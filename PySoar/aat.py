from task import Task
from generalFunctions import determine_distance, pygeodesy_determine_destination, det_bearing,\
    pygeodesy_calculate_distance, det_time_difference, enl_time_exceeded, enl_value_exceeded


class AAT(Task):
    def __init__(self, task_information):
        super(AAT, self).__init__(task_information)

        self.t_min = task_information['t_min']
        self.nominal_distances = []
        self.minimal_distances = []  # not yet filled
        self.maximum_distances = []  # not yet filled

        self.set_task_distances()

    def set_task_distances(self):
        for leg in range(self.no_legs):
            begin = self.taskpoints[leg]
            end = self.taskpoints[leg + 1]  # next is built in name

            distance = determine_distance(begin.LCU_line, end.LCU_line, 'tsk', 'tsk')
            self.nominal_distances.append(distance)

            # unfortunately calculating the minimum and maximum distances seem to be a separate optimization problem
            # it is not simply the distance on the angle bisector
            # eg. cae-open-benelux-gliding-championships-2016/results/club/task-2-on-2016-05-19/daily

    def apply_rules(self, trace, trip, trace_settings):
        self.determine_trip_fixes(trace, trip, trace_settings)
        self.refine_start(trip, trace)
        self.determine_trip_distances(trip)

    def add_aat_sector_distance(self, sector_distances, taskpoint_index, fix_index, distance):
        if len(sector_distances[2]) < fix_index + 1:
            sector_distances[2].append(distance)
        else:
            sector_distances[2][fix_index] = distance

    def add_aat_sector_fix(self, sector_fixes, taskpoint_index, fix):
        if len(sector_fixes) < (taskpoint_index + 1):
            sector_fixes.append([fix])
        else:
            sector_fixes[taskpoint_index].append(fix)

    def get_sector_fixes(self, trace, trace_settings):

        # following assumptions are currently in place
        # - outlanding inside sector leads to wrong distance

        current_leg = -1  # not yet started
        sector_fixes = []

        enl_time = 0
        enl_first_fix = None
        enl_outlanding = False

        for trace_index, fix in enumerate(trace[:-1]):

            # check ENL when aircraft logs ENL and no ENL outlanding has taken place
            if trace_settings['enl_indices'] is not None and not enl_outlanding:
                if enl_value_exceeded(fix, trace_settings['enl_indices']):
                    if enl_first_fix is None:
                        enl_first_fix = fix
                    fix2 = trace[trace_index + 1]
                    enl_time += det_time_difference(fix, fix2, 'pnt', 'pnt')
                    if enl_time_exceeded(enl_time):
                        enl_outlanding = True
                        if current_leg > 0:
                            break
                else:
                    enl_time = 0
                    enl_first_fix = None

            if current_leg == -1:  # before start
                fix2 = trace[trace_index + 1]
                if self.started(fix, fix2):
                    self.add_aat_sector_fix(sector_fixes, 0, fix2)  # at task start point
                    current_leg = 0
                    enl_outlanding = False
                    enl_first_fix = None
                    enl_time = 0
            elif current_leg == 0:  # first leg, re-start still possible
                fix2 = trace[trace_index + 1]
                if self.started(fix, fix2):  # restart
                    sector_fixes[0] = [fix2]  # at task start point
                    current_leg = 0
                    enl_outlanding = False
                    enl_first_fix = None
                    enl_time = 0
                elif self.taskpoints[1].inside_sector(fix):  # first sector
                    if enl_outlanding:
                        break  # break when ENL is used and not restarted
                    self.add_aat_sector_fix(sector_fixes, 1, fix)
                    current_leg += 1
            elif 0 < current_leg < self.no_legs - 1:  # at least second leg, no re-start possible
                if self.taskpoints[current_leg].inside_sector(fix):  # previous taskpoint
                    self.add_aat_sector_fix(sector_fixes, current_leg, fix)
                elif self.taskpoints[current_leg + 1].inside_sector(fix):  # next taskpoint
                    self.add_aat_sector_fix(sector_fixes, current_leg + 1, fix)
                    current_leg += 1
            elif current_leg == self.no_legs - 1:  # last leg
                fix2 = trace[trace_index + 1]
                if self.taskpoints[current_leg].inside_sector(fix):
                    self.add_aat_sector_fix(sector_fixes, current_leg, fix)
                elif self.finished(fix, fix2):
                    sector_fixes.append([fix2])  # at task finish point
                    current_leg = self.no_legs
                    break

        if enl_outlanding:
            return sector_fixes, enl_first_fix
        else:
            return sector_fixes, None

    def reduce_sector_fixes(self, sector_fixes, max_fixes_sector):
        reduced_sector_fixes = []
        for sector in range(len(sector_fixes)):
            reduction_factor = len(sector_fixes[sector]) / max_fixes_sector + 1
            reduced_sector_fixes.append(sector_fixes[sector][0::reduction_factor])

        return reduced_sector_fixes

    def refine_max_distance_fixes(self, sector_fixes, max_distance_fixes, outlanding):
        # look around fixes whether more precise fixes can be found, increasing the distance

        refinement_fixes = 10  # this amount before and this amount after the provided fix

        refined_sector_fixes = [[max_distance_fixes[0]]]  # already include start fix

        for leg in range(self.no_legs):

            if outlanding and leg > len(sector_fixes)-2:
                break

            max_distance_index = sector_fixes[leg+1].index(max_distance_fixes[leg+1])

            if max_distance_index >= refinement_fixes:
                refinement_start = max_distance_index - refinement_fixes
            else:
                refinement_start = 0

            if max_distance_index + refinement_fixes + 1 <= len(sector_fixes[leg + 1]):
                refinement_end = max_distance_index + refinement_fixes + 1
            else:
                refinement_end = len(sector_fixes[leg + 1]) + 1

            refined_sector_fixes.append(sector_fixes[leg+1][refinement_start:refinement_end])

        return self.compute_max_distance_fixes(refined_sector_fixes, outlanding)

    def calculate_distance_completed_leg(self, leg, start_tp_fix, end_tp_fix):
        # room for improvement:
        # by using LatLon objects instead of records, the switch case can be reduced
        # since pnt are now the same as tsk records
        if leg == 0:  # take start-point of task
            distance = determine_distance(self.taskpoints[0].LCU_line, end_tp_fix, 'tsk', 'pnt')
        elif leg == self.no_legs - 1:  # take finish-point of task
            distance = determine_distance(start_tp_fix, self.taskpoints[-1].LCU_line, 'pnt', 'tsk')
        else:
            distance = determine_distance(start_tp_fix, end_tp_fix, 'pnt', 'pnt')

        return distance

    def calculate_distance_outlanding_leg(self, leg, start_tp_fix, outlanding_fix):
        # room for improvement:
        # by using LatLon objects instead of records, the switch case can be reduced
        # since pnt are now the same as tsk records
        if leg == 0:
            tp1 = self.taskpoints[leg + 1]

            bearing = det_bearing(tp1.LCU_line, outlanding_fix, 'tsk', 'pnt')
            closest_area_point = pygeodesy_determine_destination(tp1.LCU_line, 'tsk', bearing,
                                                                 tp1.r_max)

            distance = pygeodesy_calculate_distance(self.taskpoints[0].LCU_line, 'tsk',
                                                    closest_area_point)
            distance -= pygeodesy_calculate_distance(outlanding_fix, 'pnt', closest_area_point)

        elif leg == self.no_legs - 1:  # take finish-point of task
            distance = determine_distance(start_tp_fix, self.taskpoints[leg + 1].LCU_line, 'pnt', 'tsk')
            distance -= determine_distance(self.taskpoints[leg + 1].LCU_line, outlanding_fix, 'tsk', 'pnt')
        else:
            tp1 = self.taskpoints[leg + 1]

            bearing = det_bearing(tp1.LCU_line, outlanding_fix, 'tsk', 'pnt')
            closest_area_point = pygeodesy_determine_destination(tp1.LCU_line, 'tsk', bearing,
                                                                 tp1.r_max)

            if leg == 0:
                distance = pygeodesy_calculate_distance(self.taskpoints[0].LCU_line, 'tsk',
                                                        closest_area_point)
            else:
                distance = pygeodesy_calculate_distance(start_tp_fix, 'pnt', closest_area_point)
            distance -= pygeodesy_calculate_distance(outlanding_fix, 'pnt', closest_area_point)

        return distance

    def compute_max_distance_fixes(self, sector_fixes, outlanding):
        distances = [[]] * len(sector_fixes)
        distances[0] = [[0, 0]] * len(sector_fixes[0])

        legs_started = len(sector_fixes) - 1  # not necessarily finished
        for leg in range(legs_started):

            distances[leg + 1] = [[0, 0] for i in range(len(sector_fixes[leg + 1]))]

            for fix2_index, fix2 in enumerate(sector_fixes[leg + 1]):
                for fix1_index, fix1 in enumerate(sector_fixes[leg]):

                    if outlanding and leg == legs_started-1:  # outlanding leg
                        distance = self.calculate_distance_outlanding_leg(leg, fix1, fix2)
                    else:
                        distance = self.calculate_distance_completed_leg(leg, fix1, fix2)

                    total_distance = distances[leg][fix1_index][0] + distance
                    if total_distance > distances[leg + 1][fix2_index][0]:
                        distances[leg + 1][fix2_index][0] = total_distance
                        distances[leg + 1][fix2_index][1] = fix1_index

        # determine index on last sector/outlanding-group with maximum distance
        max_dist = 0
        maximized_dist_index = None
        for i, distance in enumerate(distances[-1]):
            if distance[0] > max_dist:
                max_dist = distance[0]
                maximized_dist_index = i

        index = maximized_dist_index
        max_distance_fixes = [sector_fixes[-1][index]]

        for leg in list(reversed(range(legs_started))):
            index = distances[leg + 1][index][1]
            max_distance_fixes.insert(0, sector_fixes[leg][index])

        return max_distance_fixes

    def add_outlanding_fixes(self, trace, sector_fixes, enl_outlanding_fix):
        last_sector_fix = sector_fixes[-1][-1]
        last_sector_index = trace.index(last_sector_fix)

        if enl_outlanding_fix is not None:
            enl_outlanding_index = trace.index(enl_outlanding_fix)

            if enl_outlanding_index > last_sector_index:
                sector_fixes.append(trace[last_sector_index + 1: enl_outlanding_index + 1])
        else:
            sector_fixes.append(trace[last_sector_index+1:])

    def determine_trip_fixes(self, trace, trip, trace_settings):  # trace settings for ENL

        sector_fixes, enl_outlanding_fix = self.get_sector_fixes(trace, trace_settings)

        if enl_outlanding_fix is not None:
            trip.enl_fix = enl_outlanding_fix

        outlanded = False
        if len(sector_fixes) != self.no_legs+1:
            outlanded = True
            self.add_outlanding_fixes(trace, sector_fixes, enl_outlanding_fix)

        # reduce sector fixes to reduce computational cost
        reduced_sector_fixes = self.reduce_sector_fixes(sector_fixes, max_fixes_sector=300)

        # compute maximum distance fixes
        max_distance_fixes = self.compute_max_distance_fixes(reduced_sector_fixes, outlanded)

        # refine these fixes
        max_distance_fixes = self.refine_max_distance_fixes(sector_fixes, max_distance_fixes, outlanded)

        if outlanded:
            trip.fixes = max_distance_fixes[:-1]
            trip.outlanding_fix = max_distance_fixes[-1]
        else:
            trip.fixes = max_distance_fixes

    # candidate for trip class?
    def determine_trip_distances(self, trip):

        # todo: formalize distance correction for start and finish (inside taskpoint?)

        # can this be replaced by call to self.calculate_distance_completed_leg?
        for fix1_index, fix1 in enumerate(trip.fixes[:-1]):
            if fix1_index == 0:
                fix2 = trip.fixes[fix1_index + 1]
                distance = determine_distance(self.taskpoints[0].LCU_line, fix2, 'tsk', 'pnt')
                if self.taskpoints[0].distance_correction == 'shorten_legs':
                    distance -= self.taskpoints[0].r_max
            elif fix1_index == self.no_legs-1:
                distance = determine_distance(fix1, self.taskpoints[-1].LCU_line, 'pnt', 'tsk')
                if self.taskpoints[-1].distance_correction == 'shorten_legs':
                    distance -= self.taskpoints[-1].r_max
            else:
                fix2 = trip.fixes[fix1_index + 1]
                distance = determine_distance(fix1, fix2, 'pnt', 'pnt')

            trip.distances.append(distance)

        if trip.outlanded():
            leg = trip.outlanding_leg()
            distance = self.calculate_distance_outlanding_leg(leg, trip.fixes[-1], trip.outlanding_fix)
            trip.distances.append(distance)
