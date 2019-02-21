import os
import logging

from .models.facade_segment import FacadeSegment
from .models.segment import Segment
from .models.mimic_segment import MimicSegment
from .context import CXT_MISSING_STRATEGY_KEY
from .lambda_launcher import LambdaContext


log = logging.getLogger(__name__)


class ServerlessLambdaContext(LambdaContext):
    """
    Context used specifically for running middlewares on Lambda through the
    Serverless design. This context is built on top of the LambdaContext, but
    creates a Segment masked as a Subsegment known as a MimicSegment underneath
    the Lambda-generated Facade Segment. This ensures that middleware->recorder's
    consequent calls to "put_segment()" will not throw exceptions but instead create
    subsegments underneath the lambda-generated Facade Segment. This context also
    ensures that FacadeSegments exist through underlying calls to _refresh_context().
    """
    def __init__(self, context_missing='RUNTIME_ERROR'):
        super(ServerlessLambdaContext, self).__init__()

        strategy = os.getenv(CXT_MISSING_STRATEGY_KEY, context_missing)
        self._context_missing = strategy

    def put_segment(self, segment):
        """
        Convert the segment into a mimic segment and append it to FacadeSegment's subsegment list.
        :param Segment segment:
        """
        # When putting a segment, convert it to a mimic segment and make it a child of the Facade Segment.
        parent_facade_segment = self.__get_facade_entity()  # type: FacadeSegment
        mimic_segment = MimicSegment(parent_facade_segment, segment)
        parent_facade_segment.add_subsegment(mimic_segment)
        super(LambdaContext, self).put_segment(mimic_segment)

    def end_segment(self, end_time=None):
        """
        Close the MimicSegment
        """
        # Close the last mimic segment opened then remove it from our facade segment.
        mimic_segment = self.get_trace_entity()
        super(LambdaContext, self).end_segment(end_time)
        if type(mimic_segment) == MimicSegment:
            # The facade segment can only hold mimic segments.
            facade_segment = self.__get_facade_entity()
            facade_segment.remove_subsegment(mimic_segment)

    def put_subsegment(self, subsegment):
        """
        Appends the subsegment as a subsegment of either the mimic segment or
        another subsegment if they are the last opened entity.
        :param subsegment: The subsegment to to be added as a subsegment.
        """
        super(LambdaContext, self).put_subsegment(subsegment)

    def end_subsegment(self, end_time=None):
        """
        End the current subsegment. In our case, subsegments
        will either be a subsegment of a mimic segment or another
        subsegment.
        :param int end_time: epoch in seconds. If not specified the current
            system time will be used.
        :return: True on success, false if no parent mimic segment/subsegment is found.
        """
        return super(LambdaContext, self).end_subsegment(end_time)

    def __get_facade_entity(self):
        """
        Retrieves the Facade segment from thread local. This facade segment should always be present
        because it was generated by the Lambda Container.
        :return: FacadeSegment
        """
        self._refresh_context()
        facade_segment = self._local.segment  # type: FacadeSegment
        return facade_segment

    def get_trace_entity(self):
        """
        Return the latest entity added. In this case, it'll either be a Mimic Segment or
        a subsegment. Facade Segments are never returned.
        If no mimic segments or subsegments were ever passed in, throw the default
        context missing error.
        :return: Entity
        """
        # Call to Context.get_trace_entity() returns the latest mimic segment/subsegment if they exist.
        # Otherwise, returns None through the following way:
        # No mimic segment/subsegment exists so Context calls LambdaContext's handle_context_missing().
        # By default, Lambda's method returns no-op, so it will return None to ServerlessLambdaContext.
        # Take that None as an indication to return the rightful handle_context_missing(), otherwise
        # return the entity.
        entity = super(LambdaContext, self).get_trace_entity()
        if entity is None:
            return super(LambdaContext, self).handle_context_missing()
        else:
            return entity

    def set_trace_entity(self, trace_entity):
        """
        Stores the input trace_entity to local context. It will overwrite all
        existing ones if there is any. If the entity passed in is a segment,
        it will automatically be converted to a mimic segment.
        """
        if type(trace_entity) == Segment:
            # Convert to a mimic segment.
            parent_facade_segment = self.__get_facade_entity()  # type: FacadeSegment
            converted_segment = MimicSegment(parent_facade_segment, trace_entity)
            mimic_segment = converted_segment
        else:
            # Should be a Mimic Segment. If it's a subsegment, grandparent Context's
            # behavior would be invoked.
            mimic_segment = trace_entity

        super(LambdaContext, self).set_trace_entity(mimic_segment)
        self.__get_facade_entity().subsegments = [mimic_segment]

    def _is_subsegment(self, entity):
        return super(ServerlessLambdaContext, self)._is_subsegment(entity) and type(entity) != MimicSegment

    @property
    def context_missing(self):
        return self._context_missing

    @context_missing.setter
    def context_missing(self, value):
        self._context_missing = value
